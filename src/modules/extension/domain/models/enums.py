import enum


class InstallStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    BLACKLISTED = "BLACKLISTED"
