import enum


class Role(str, enum.Enum):
    ADMIN = "ADMIN"
    IT_ANALYST = "IT_ANALYST"


class TokenType(str, enum.Enum):
    ACCESS = "ACCESS"
    REFRESH = "REFRESH"
