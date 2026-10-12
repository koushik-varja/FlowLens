"""create datasets table"""

from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "datasets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("events_json", sa.Text(), nullable=False),
        sa.Column("quality_json", sa.Text(), nullable=False),
    )
    op.create_index("ix_datasets_name", "datasets", ["name"])
    op.create_index("ix_datasets_created_at", "datasets", ["created_at"])


def downgrade():
    op.drop_index("ix_datasets_created_at", table_name="datasets")
    op.drop_index("ix_datasets_name", table_name="datasets")
    op.drop_table("datasets")
