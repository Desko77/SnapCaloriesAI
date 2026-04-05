"""confirm_all_existing_meals

Revision ID: f48f2cac1c85
Revises: 4c1e66dec216
Create Date: 2026-04-05 12:20:32.993095

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f48f2cac1c85'
down_revision: Union[str, Sequence[str], None] = '4c1e66dec216'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("UPDATE meal_logs SET is_confirmed = 1 WHERE is_confirmed = 0")


def downgrade() -> None:
    pass
