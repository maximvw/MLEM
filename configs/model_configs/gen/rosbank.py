import ml_collections


def model_configs():
    config = ml_collections.ConfigDict()

    config.model_name = "SeqGen"
    config.predict_head = "Linear"  # Linear or Identity

    ### EMBEDDINGS ###
    # features_emb_dim is dimension of nn.Embedding applied to categorical features
    config.features_emb_dim = 8
    config.use_numeric_emb = False
    config.features_emb_dim = 8

    ### ENCODER ###
    config.encoder = "GRU"
    config.encoder_hidden = 3
    config.encoder_num_layers = 1

    ### TRANSFORMER ENCODER ###
    config.encoder_num_heads = 1

    ### DECODER ###
    config.decoder = "GRU"
    config.decoder_hidden = 3
    config.decoder_num_layers = 1

    ### TRANSFORMER DECODER ###
    config.decoder_heads = 1

    ### NORMALIZATIONS ###
    config.pre_encoder_norm = "Identity"
    config.post_encoder_norm = "Identity"
    config.decoder_norm = "Identity"
    config.encoder_norm = "Identity"

    ### DROPOUT ###
    config.after_enc_dropout = 0.05

    ### ACTIVATION ###
    config.activation = "ReLU"

    ### TIME ###
    config.use_deltas = True
    config.delta_weight = 5

    ### LOSS ###
    config.mse_weight = 1
    config.CE_weight = 1

    ### DEVICE + OPTIMIZER ###
    config.device = "cpu"

    config.lr = 3e-3
    config.weight_decay = 1e-3
    config.cv_splits = 5

    config.use_discriminator = False
    config.comments = ""
    return config
