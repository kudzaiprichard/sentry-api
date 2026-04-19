"""add submitted_by_install to emails

Revision ID: 40b1d83f51bc
Revises: d872777cf62a
Create Date: 2026-04-20 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '40b1d83f51bc'
down_revision: Union[str, Sequence[str], None] = 'd872777cf62a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'emails',
        sa.Column('submitted_by_install', sa.UUID(), nullable=True),
    )
    op.create_index(
        op.f('ix_emails_submitted_by_install'),
        'emails',
        ['submitted_by_install'],
        unique=False,
    )
    op.create_foreign_key(
        'fk_emails_submitted_by_install_extension_installs',
        'emails',
        'extension_installs',
        ['submitted_by_install'],
        ['id'],
        ondelete='SET NULL',
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        'fk_emails_submitted_by_install_extension_installs',
        'emails',
        type_='foreignkey',
    )
    op.drop_index(op.f('ix_emails_submitted_by_install'), table_name='emails')
    op.drop_column('emails', 'submitted_by_install')
