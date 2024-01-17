import logging
from argparse import ArgumentParser
from datetime import datetime
from pathlib import Path

import torch
import sys
import pickle

sys.path.append("../../")

from configs.data_configs.sber_contrastive import data_configs
from configs.model_configs.supervised.sber import model_configs
from src.data_load.dataloader import create_data_loaders, create_test_loader
from src.trainers.trainer_contrastive import SimpleTrainerContrastive
from src.trainers.randomness import seed_everything
import src.models.base_models


def run_experiment(run_name, device, total_epochs, conf, model_conf, resume, log_dir):
    ### SETUP LOGGING ###
    ch = logging.StreamHandler()
    cons_lvl = getattr(logging, "warning".upper())
    ch.setLevel(cons_lvl)
    cfmt = logging.Formatter("{levelname:8} - {asctime} - {message}", style="{")
    ch.setFormatter(cfmt)

    Path(log_dir).mkdir(parents=True, exist_ok=True)
    log_file = Path(log_dir) / f"{run_name}.log"
    fh = logging.FileHandler(log_file)
    file_lvl = getattr(logging, "info".upper())
    fh.setLevel(file_lvl)
    ffmt = logging.Formatter(
        "{levelname:8} - {process: ^6} - {name: ^16} - {asctime} - {message}",
        style="{",
    )
    fh.setFormatter(ffmt)

    logger = logging.getLogger("event_seq")
    logger.setLevel(min(file_lvl, cons_lvl))
    logger.addHandler(ch)
    logger.addHandler(fh)

    ### Fix randomness ###
    # os.environ["CUBLAS_WORKSPACE_CONFIG"] = ":4096:8"
    seed_everything(
        conf.client_list_shuffle_seed,
        avoid_benchmark_noise=True,
        only_deterministic_algorithms=False,
    )

    ### Create loaders and train ###
    train_loader, valid_loader = create_data_loaders(conf, supervised=False)

    model = getattr(src.models.base_models, model_conf.model_name)
    net = model(model_conf=model_conf, data_conf=conf)
    opt = torch.optim.Adam(
        net.parameters(), model_conf.lr, weight_decay=model_conf.weight_decay
    )
    trainer = SimpleTrainerContrastive(
        model=net,
        optimizer=opt,
        train_loader=train_loader,
        val_loader=valid_loader,
        run_name=run_name,
        ckpt_dir=Path(__file__).parent / "ckpt",
        ckpt_replace=True,
        ckpt_resume=resume,
        ckpt_track_metric="total_loss",
        metrics_on_train=False,
        total_epochs=total_epochs,
        device=device,
        model_conf=model_conf,
    )

    ckpt_path = Path(__file__).parent / "ckpt" / run_name
    with open(ckpt_path / "model_config.pkl", "wb") as f:
        pickle.dump(model_conf, f)
    with open(ckpt_path / "data_config.pkl", "wb") as f:
        pickle.dump(conf, f)

    ### RUN TRAINING ###
    trainer.run()


if __name__ == "__main__":
    parser = ArgumentParser()
    parser.add_argument("--run-name", help="run name for Trainer", default=None)
    parser.add_argument(
        "--console-log",
        help="console log level",
        choices=["debug", "info", "warning", "error", "critical"],
        default="warning",
    )
    parser.add_argument(
        "--file-log",
        help="file log level",
        choices=["debug", "info", "warning", "error", "critical"],
        default="info",
    )
    parser.add_argument("--device", help="torch device to run on", default="cpu")
    parser.add_argument(
        "--log-dir",
        help="directory to write log file to",
        default="./logs",
    )
    parser.add_argument(
        "--total-epochs",
        help="total number of epochs to train",
        type=int,
        required=True,
    )
    parser.add_argument(
        "--resume",
        help="path to checkpoint to resume from",
        default=None,
    )
    args = parser.parse_args()

    run_name = args.run_name or "mtand"
    run_name += f"_{datetime.now():%F_%T}"

    ### TRAINING SETUP ###
    conf = data_configs()
    model_conf = model_configs()

    run_experiment(
        run_name,
        args.device,
        args.total_epochs,
        conf,
        model_conf,
        args.resume,
        args.log_dir,
    )