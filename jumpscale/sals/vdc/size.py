from enum import Enum

S3_NO_DATA_NODES = 6
S3_NO_PARITY_NODES = 4
MINIO_CPU = 2
MINIO_MEMORY = 4 * 1024  # in MB
MINIO_DISK = 4 * 1024  # in MB


class K8SNodeFlavor(Enum):
    SMALL = 1
    MEDIUM = 2
    BIG = 3


K8S_SIZES = {
    K8SNodeFlavor.SMALL: {"cru": 1, "mru": 2, "sru": 25},
    K8SNodeFlavor.MEDIUM: {"cru": 2, "mru": 4, "sru": 50},
    K8SNodeFlavor.BIG: {"cru": 4, "mru": 8, "sru": 50},
}


class S3ZDBSize(Enum):
    SMALL = 1
    MEDIUM = 2
    BIG = 3


S3_ZDB_SIZES = {
    S3ZDBSize.SMALL: {"sru": 3 * 1024},
    S3ZDBSize.MEDIUM: {"sru": 10 * 1024},
    S3ZDBSize.BIG: {"sru": 20 * 1024},
}


class VDCFlavor(Enum):
    SILVER = "silver"
    GOLD = "gold"
    PLATINUM = "platinum"


VDC_FLAFORS = {
    VDCFlavor.SILVER: {
        "k8s": {"no_nodes": 1, "size": K8SNodeFlavor.SMALL, "dedicated": False},
        "s3": {"size": S3ZDBSize.SMALL},
    },
    VDCFlavor.GOLD: {
        "k8s": {"no_nodes": 2, "size": K8SNodeFlavor.MEDIUM, "dedicated": False},
        "s3": {"size": S3ZDBSize.MEDIUM},
    },
    VDCFlavor.PLATINUM: {
        "k8s": {"no_nodes": 2, "size": K8SNodeFlavor.BIG, "dedicated": True},
        "s3": {"size": S3ZDBSize.BIG},
    },
}
