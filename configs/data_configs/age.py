from pathlib import Path

import ml_collections


def data_configs():
    config = ml_collections.ConfigDict()

    ########## DATA ##############

    config.train_path = (
        Path(__file__).parent.parent.parent
        / "experiments"
        / "age"
        / "data"
        / "train_trx.parquet"
    )

    config.test_path = (
        Path(__file__).parent.parent.parent
        / "experiments"
        / "age"
        / "data"
        / "test_trx.parquet"
    )

    config.track_metric = "accuracy"

    config.client_list_shuffle_seed = (
        0  # 0xAB0BA  # seed for splitting data to train and validation
    )
    config.valid_size = 0.1  # validation size
    config.col_id = "client_id"  # column defining ids. used for sorting data

    features = config.features = ml_collections.ConfigDict()
    # dict below should define all the features that are not numeric with names as keys.
    # "in" parameter is used to clip values at the input.
    # have not figured out the purpose of "out"
    features.embeddings = {
        "small_group": {"in": 202, "out": 203, "max_value": 203},
    }
    # all numeric features are defined here as keys
    # seem like its value is technical and is not used anywhere
    features.numeric_values = {
        "amount_rur": "Identity",
    }

    config.ckpt_path = (
        Path(__file__).parent.parent.parent
        / "experiments"
        / "physionet"
        / "ckpt"
        / "Tr_1l_2h_LN_GR128+LN_2023-09-20_09:32:45"
        / "epoch: 0033 - total_loss: 0.2984 - roc_auc: 0.8421 - loss: 0.2629.ckpt"
    )

    # name of target col
    features.target_col = "target"
    config.num_classes = 4

    ### TIME ###
    config.max_time = 729.0
    config.min_time = 0.0

    # train specific parameters
    train = config.train = ml_collections.ConfigDict()
    # validation specific
    val = config.val = ml_collections.ConfigDict()
    # test params
    test = config.test = ml_collections.ConfigDict()

    train.split_strategy = {"split_strategy": "NoSplit"}
    val.split_strategy = {"split_strategy": "NoSplit"}
    test.split_strategy = {"split_strategy": "NoSplit"}

    # dropout
    train.dropout = 0.05

    # seq len
    train.max_seq_len = 1000
    val.max_seq_len = 1000
    test.max_seq_len = 1000

    train.num_workers = 1
    val.num_workers = 1
    test.num_workers = 1

    train.batch_size = 128
    val.batch_size = 128
    test.batch_size = 16

    return config
