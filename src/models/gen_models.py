import torch
import torch.nn as nn
from . import preprocessors as prp
from ..trainers.losses import get_loss
import numpy as np
from torch.autograd import Variable


class L2Normalization(nn.Module):
    def __init__(self):
        super(L2Normalization, self).__init__()

    def forward(self, x):
        return x.div(torch.norm(x, dim=1).view(-1, 1))


class BaseMixin(nn.Module):
    def __init__(self, model_conf, data_conf):
        super().__init__()
        self.model_conf = model_conf
        self.data_conf = data_conf

        ### PROCESSORS ###
        self.processor = prp.FeatureProcessor(
            model_conf=model_conf, data_conf=data_conf
        )

        ### INPUT SIZE ###
        all_emb_size = self.model_conf.features_emb_dim * len(
            self.data_conf.features.embeddings
        )
        self.all_numeric_size = len(self.data_conf.features.numeric_values)
        self.input_dim = (
            all_emb_size + self.all_numeric_size + self.model_conf.use_deltas
        )

        ### NORMS ###
        self.pre_encoder_norm = getattr(nn, self.model_conf.pre_encoder_norm)(
            self.input_dim
        )
        self.post_encoder_norm = getattr(nn, self.model_conf.post_encoder_norm)(
            self.model_conf.encoder_hidden
        )
        self.decoder_norm = getattr(nn, self.model_conf.decoder_norm)(
            self.model_conf.decoder_hidden
        )
        self.encoder_norm = getattr(nn, self.model_conf.encoder_norm)(
            self.model_conf.encoder_hidden
        )

        ### ENCODER ###
        if self.model_conf.encoder == "GRU":
            self.encoder = nn.GRU(
                self.input_dim,
                self.model_conf.encoder_hidden,
                batch_first=True,
                num_layers=self.model_conf.encoder_num_layers,
            )
        elif self.model_conf.encoder == "LSTM":
            self.encoder = nn.LSTM(
                self.input_dim,
                self.model_conf.encoder_hidden,
                batch_first=True,
                num_layers=self.model_conf.encoder_num_layers,
            )
        elif self.model_conf.encoder == "TR":
            self.encoder_proj = nn.Linear(
                self.input_dim, self.model_conf.encoder_hidden
            )
            encoder_layer = nn.TransformerEncoderLayer(
                d_model=self.model_conf.encoder_hidden,
                nhead=self.model_conf.encoder_num_heads,
                batch_first=True,
            )

            self.encoder = nn.TransformerEncoder(
                encoder_layer,
                self.model_conf.encoder_num_layers,
                norm=self.encoder_norm,
                enable_nested_tensor=True,
                mask_check=True,
            )

        ### DECODER ###
        if self.model_conf.decoder == "GRU":
            self.decoder = DecoderGRU(
                input_size=self.input_dim,
                hidden_size=self.model_conf.decoder_hidden,
                global_hidden_size=self.model_conf.encoder_hidden,
                num_layers=self.model_conf.decoder_num_layers,
            )
        elif self.model_conf.decoder == "TR":
            decoder_layer = nn.TransformerDecoderLayer(
                d_model=self.model_conf.decoder_hidden,
                nhead=self.model_conf.decoder_heads,
                batch_first=True,
            )
            self.decoder = nn.TransformerDecoder(
                decoder_layer,
                num_layers=self.model_conf.decoder_num_layers,
                norm=self.decoder_norm,
            )
            self.decoder_proj = nn.Linear(
                self.input_dim, self.model_conf.decoder_hidden
            )

        ### DROPOUT ###
        self.global_hid_dropout = nn.Dropout(self.model_conf.after_enc_dropout)

        ### ACTIVATION ###
        self.act = nn.GELU()

        ### OUT PROJECTION ###
        self.out_proj = nn.Linear(self.model_conf.decoder_hidden, self.input_dim)

        ### LOSS ###
        self.embedding_predictor = EmbeddingPredictor(
            model_conf=self.model_conf, data_conf=self.data_conf
        )
        self.mse_fn = torch.nn.MSELoss(reduction="none")
        self.ce_fn = torch.nn.CrossEntropyLoss(
            reduction="mean", ignore_index=0, label_smoothing=0.15
        )

    def loss(self, output, ground_truth):
        """
        output: Dict that is outputed from forward method
        """
        gt_embedding = output["x"][:, 1:, :]
        pred = output["pred"]
        if self.model_conf.use_deltas:
            pred_delta = pred[:, :, -1].squeeze(-1)
            pred = pred[:, :, :-1]
            gt_embedding = gt_embedding[:, :, :-1]

        # MSE
        total_mse_loss = 0
        num_val_feature = self.all_numeric_size
        for key, values in output["input_batch"].payload.items():
            if not key in self.processor.emb_names:
                gt_val = values.float()[:, 1:]
                pred_val = pred[:, :, -num_val_feature]

                mse_loss = self.mse_fn(
                    gt_val,
                    pred_val,
                )
                mask = gt_val != 0
                masked_mse = mse_loss * mask
                total_mse_loss += (
                    masked_mse.sum(dim=1) / (mask != 0).sum(dim=1)
                ).mean()
                num_val_feature -= 1

        # DELTA MSE
        if self.model_conf.use_deltas:
            gt_delta = output["time_steps"].diff(1)
            delta_mse = self.mse_fn(gt_delta, pred_delta)
            mask = output["time_steps"] != -1
            delta_masked = delta_mse * mask[:, 1:]
            delta_mse = delta_masked.sum() / (mask[:, 1:] != 0).sum()
        else:
            delta_mse = 0

        # CROSS ENTROPY
        cross_entropy_losses = self.embedding_predictor.loss(
            output["emb_dist"], output["input_batch"]
        )
        total_ce_loss = torch.sum(
            torch.cat([value.unsqueeze(0) for _, value in cross_entropy_losses.items()])
        )

        losses_dict = {
            "total_mse_loss": total_mse_loss,
            "total_CE_loss": total_ce_loss,
            "delta_loss": self.model_conf.delta_weight * delta_mse,
        }
        losses_dict.update(cross_entropy_losses)

        total_loss = (
            self.model_conf.mse_weight * losses_dict["total_mse_loss"]
            + self.model_conf.CE_weight * total_ce_loss
            + self.model_conf.delta_weight * delta_mse
        )
        losses_dict["total_loss"] = total_loss

        return losses_dict


class SeqGen(BaseMixin):
    def __init__(self, model_conf, data_conf):
        super().__init__(model_conf=model_conf, data_conf=data_conf)

    def forward(self, padded_batch):
        x, time_steps = self.processor(padded_batch)
        if self.model_conf.use_deltas:
            gt_delta = time_steps.diff(1)
            delta_feature = torch.cat(
                [gt_delta, torch.zeros(x.size()[0], 1, device=gt_delta.device)], dim=1
            )
            x = torch.cat([x, delta_feature.unsqueeze(-1)], dim=-1)

        if self.model_conf.encoder in ("GRU", "LSTM"):
            all_hid, hn = self.encoder(self.pre_encoder_norm(x))
            lens = padded_batch.seq_lens - 1
            last_hidden = self.post_encoder_norm(all_hid[:, lens, :].diagonal().T)
        elif self.model_conf.encoder == "TR":
            x_proj = self.encoder_proj(x)
            enc_out = self.encoder(x_proj)
            last_hidden = enc_out[:, 0, :]

        last_hidden = self.global_hid_dropout(last_hidden)

        if self.model_conf.decoder == "GRU":
            dec_out = self.decoder(x, last_hidden)

        elif self.model_conf.decoder == "TR":
            x_proj = self.decoder_proj(x)
            mask = torch.nn.Transformer.generate_square_subsequent_mask(
                x.size(1), device=x.device
            )
            dec_out = self.decoder(
                tgt=x_proj,
                memory=last_hidden.unsqueeze(1),
                tgt_mask=mask,
            )

        out = self.out_proj(dec_out)[:, :-1, :]
        emb_dist = self.embedding_predictor(out)

        return {
            "x": x,
            "time_steps": time_steps,
            "pred": out,
            "input_batch": padded_batch,
            "emb_dist": emb_dist,
            "latent": last_hidden,
        }


class EmbeddingPredictor(nn.Module):
    def __init__(self, model_conf, data_conf):
        super().__init__()
        self.model_conf = model_conf
        self.data_conf = data_conf

        self.criterion = nn.CrossEntropyLoss(reduction="mean", ignore_index=0)

        self.emb_names = list(self.data_conf.features.embeddings.keys())
        self.num_embeds = len(self.emb_names)
        self.categorical_len = self.num_embeds * self.model_conf.features_emb_dim

        self.init_embed_predictors()

    def init_embed_predictors(self):
        self.embed_predictors = nn.ModuleDict()

        for name in self.emb_names:
            vocab_size = self.data_conf.features.embeddings[name]["max_value"]
            self.embed_predictors[name] = nn.Linear(
                self.model_conf.features_emb_dim, vocab_size
            )

    def forward(self, x_recon):
        batch_size, seq_len, out_dim = x_recon.size()

        resized_x = x_recon[:, :, : self.categorical_len].view(
            batch_size,
            seq_len,
            self.num_embeds,
            self.model_conf.features_emb_dim,
        )

        embeddings_distribution = {}
        for i, name in enumerate(self.emb_names):
            embeddings_distribution[name] = self.embed_predictors[name](
                resized_x[:, :, i, :]
            )

        return embeddings_distribution

    def loss(self, embedding_distribution, padded_batch):
        embed_losses = {}
        for name, dist in embedding_distribution.items():
            shifted_labels = padded_batch.payload[name].long()[:, 1:]
            embed_losses[name] = self.criterion(dist.permute(0, 2, 1), shifted_labels)

        return embed_losses


class GRUCell(nn.Module):
    def __init__(self, input_size, hidden_size, global_hidden_size, bias=True):
        super(GRUCell, self).__init__()
        self.input_size = input_size
        self.hidden_size = hidden_size
        self.bias = bias

        self.x2h = nn.Linear(input_size, 3 * hidden_size, bias=bias)
        self.h2h = nn.Linear(hidden_size, 3 * hidden_size, bias=bias)
        self.mix_global = nn.Linear(hidden_size + global_hidden_size, hidden_size)
        self.act = nn.GELU()
        self.reset_parameters()

    def reset_parameters(self):
        std = 1.0 / np.sqrt(self.hidden_size)
        for w in self.parameters():
            w.data.uniform_(-std, std)

    def forward(self, input, global_hidden, hx=None):
        # Inputs:
        #       input: of shape (batch_size, input_size)
        #       global_hidden: of shape (batch_size, global_hidden_size)
        #       hx: of shape (batch_size, hidden_size)
        # Output:
        #       hy: of shape (batch_size, hidden_size)

        if hx is None:
            hx = Variable(input.new_zeros(input.size(0), self.hidden_size))

        hx = self.act(self.mix_global(torch.cat([global_hidden, hx], dim=-1)))
        x_t = self.x2h(input)
        h_t = self.h2h(hx)

        x_reset, x_upd, x_new = x_t.chunk(3, 1)
        h_reset, h_upd, h_new = h_t.chunk(3, 1)

        reset_gate = torch.sigmoid(x_reset + h_reset)
        update_gate = torch.sigmoid(x_upd + h_upd)
        new_gate = torch.tanh(x_new + (reset_gate * h_new))

        hy = update_gate * hx + (1 - update_gate) * new_gate

        return hy


class DecoderGRU(nn.Module):
    def __init__(
        self, input_size, hidden_size, global_hidden_size, num_layers, bias=True
    ):
        super(DecoderGRU, self).__init__()

        self.input_size = input_size
        self.hidden_size = hidden_size
        self.global_hidden_size = global_hidden_size
        self.num_layers = num_layers
        self.bias = bias

        self.rnn_cell_list = nn.ModuleList()
        self.rnn_cell_list.append(
            GRUCell(
                self.input_size, self.hidden_size, self.global_hidden_size, self.bias
            )
        )
        for l in range(1, self.num_layers):
            self.rnn_cell_list.append(
                GRUCell(
                    self.hidden_size,
                    self.hidden_size,
                    self.global_hidden_size,
                    self.bias,
                )
            )

    def forward(self, input, global_hidden, hx=None, **kwargs):
        # Input of shape (batch_size, seqence length, input_size)
        #
        # Output of shape (batch_size, output_size)

        if hx is None:
            h0 = Variable(
                torch.zeros(self.num_layers, input.size(0), self.hidden_size).to(
                    input.device
                )
            )

        else:
            h0 = hx

        outs = []

        hidden = list()
        for layer in range(self.num_layers):
            hidden.append(h0[layer, :, :])

        for t in range(input.size(1)):
            for layer in range(self.num_layers):
                if layer == 0:
                    hidden_l = self.rnn_cell_list[layer](
                        input[:, t, :], global_hidden, hidden[layer]
                    )
                else:
                    hidden_l = self.rnn_cell_list[layer](
                        hidden[layer - 1], global_hidden, hidden[layer]
                    )
                hidden[layer] = hidden_l

                hidden[layer] = hidden_l

            outs.append(hidden_l.unsqueeze(1))

        return torch.cat(outs, dim=1)
