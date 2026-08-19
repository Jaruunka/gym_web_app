"""add favorite exercises

Revision ID: 8c71e5a5b2f4
Revises: 1398c4e9df6c
Create Date: 2026-08-19

"""
from alembic import op
import sqlalchemy as sa


revision = "8c71e5a5b2f4"
down_revision = "1398c4e9df6c"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "favorite_exercise",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("exercise", sa.String(length=100), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "exercise",
            name="uq_favorite_exercise_user_exercise"
        )
    )
    op.execute("ALTER TABLE favorite_exercise ENABLE ROW LEVEL SECURITY")


def downgrade():
    op.drop_table("favorite_exercise")
