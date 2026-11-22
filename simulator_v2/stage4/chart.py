"""Chart of accounts for the CAD management ledger."""

from dataclasses import dataclass

from .ledger import Account


@dataclass(frozen=True)
class ChartRow:
    account: Account
    name: str
    category: str
    normal_balance: str


CHART = (
    ChartRow(Account.WAREHOUSE, "Feed ingredient warehouse inventory", "asset", "debit"),
    ChartRow(Account.RECOVERY, "Recoverable refusal stock", "asset", "debit"),
    ChartRow(Account.WIP, "Cattle management WIP", "asset", "debit"),
    ChartRow(Account.RECEIVABLE, "Packer receivables", "asset", "debit"),
    ChartRow(Account.FEED_RECEIPT, "Feed receiving accrual", "liability", "credit"),
    ChartRow(Account.ACQUISITION, "Cattle acquisition payable", "liability", "credit"),
    ChartRow(Account.YARDAGE, "Yardage and operations accrual", "liability", "credit"),
    ChartRow(Account.VET, "Veterinary services accrual", "liability", "credit"),
    ChartRow(Account.INVOICE, "Supplier invoice differences payable", "liability", "credit"),
    ChartRow(Account.MIX, "Ingredient issue and mixing clearing", "clearing", "debit"),
    ChartRow(Account.DISTRIBUTION, "Ration distribution and bunk clearing", "clearing", "debit"),
    ChartRow(Account.NORMAL, "Feed loss allocation clearing", "clearing", "debit"),
    ChartRow(Account.PENDING, "Refusal pending classification", "clearing", "debit"),
    ChartRow(Account.OPENING, "Opening inventory and cattle WIP control", "opening_equity_control", "credit"),
    ChartRow(Account.REVENUE, "Cattle sales revenue", "revenue", "credit"),
    ChartRow(Account.PACKER, "Packer settlement adjustments", "contra_revenue", "debit"),
    ChartRow(Account.COGS, "Sold cattle cost of goods sold", "expense", "debit"),
    ChartRow(Account.MORTALITY, "Cattle mortality write-off", "expense", "debit"),
    ChartRow(Account.ABNORMAL, "Abnormal process feed losses and waste", "expense", "debit"),
    ChartRow(Account.STOCK_COUNT, "Warehouse physical count adjustments", "expense", "debit"),
    ChartRow(Account.SPOILAGE, "Warehouse spoilage", "expense", "debit"),
    ChartRow(Account.OTHER_VARIANCE, "Other operating feed variance and refusal disposal", "expense", "debit"),
    ChartRow(Account.WAREHOUSE_SHRINK, "Warehouse shrinkage", "expense", "debit"),
    ChartRow(Account.WAREHOUSE_DAMAGE, "Warehouse damage", "expense", "debit"),
)
