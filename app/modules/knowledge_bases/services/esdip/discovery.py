import io
import logging
from typing import Dict, List, Any
import pandas as pd

logger = logging.getLogger(__name__)

class LogicalTable:
    def __init__(self, sheet_name: str, start_row: int, end_row: int, dataframe: pd.DataFrame, confidence: float):
        self.sheet_name = sheet_name
        self.start_row = start_row
        self.end_row = end_row
        self.dataframe = dataframe
        self.confidence = confidence
        self.schema: Dict[str, Any] = {}
        self.headers: List[str] = []

class WorkbookDiscovery:
    """
    Stage 1: Workbook Discovery
    Reads the workbook into raw pandas DataFrames.
    """
    @staticmethod
    def discover(file_bytes: bytes, filename: str) -> Dict[str, pd.DataFrame]:
        logger.info(f"Stage 1: Workbook Discovery for {filename}")
        sheets_data = {}
        ext = filename.lower().split(".")[-1] if "." in filename else ""
        
        if ext == "csv":
            df = pd.read_csv(io.BytesIO(file_bytes))
            sheets_data["Sheet1"] = df
        elif ext in ["xlsx", "xls"]:
            xl = pd.ExcelFile(io.BytesIO(file_bytes))
            for sheet_name in xl.sheet_names:
                sheets_data[sheet_name] = xl.parse(sheet_name, header=None) # Load without assuming row 0 is header
        else:
            raise ValueError(f"Unsupported spreadsheet format: {ext}")
            
        return sheets_data


class SheetClassification:
    """
    Stage 2: Sheet Classification
    Filters out dashboards, empty sheets, etc.
    """
    @staticmethod
    def classify(sheets: Dict[str, pd.DataFrame]) -> Dict[str, pd.DataFrame]:
        logger.info(f"Stage 2: Sheet Classification")
        valid_sheets = {}
        
        for sheet_name, df in sheets.items():
            df_clean = df.dropna(how="all").dropna(how="all", axis=1)
            
            if df_clean.empty:
                logger.info(f"Sheet '{sheet_name}' classified as Empty. Skipping.")
                continue
                
            # Basic heuristic: if it has very few rows but many columns, it might be a dashboard.
            # For now, we assume it's Raw Data if it's not empty.
            logger.info(f"Sheet '{sheet_name}' classified as Raw Data.")
            valid_sheets[sheet_name] = df_clean
            
        return valid_sheets


class TableBoundaryDetection:
    """
    Stage 3: Table Boundary Detection
    Finds logical tables within a single sheet.
    """
    @staticmethod
    def detect(sheet_name: str, df: pd.DataFrame) -> List[LogicalTable]:
        logger.info(f"Stage 3: Table Boundary Detection for '{sheet_name}'")
        tables = []
        
        # Reset index to have sequential integers
        df = df.reset_index(drop=True)
        
        # Lightweight detection: for now, assume one large table per sheet.
        # Future enhancement: identify blank row gaps to split into multiple LogicalTables.
        
        # Check for first row that looks like a header (mostly strings)
        header_row_idx = 0
        for i in range(min(20, len(df))):
            row = df.iloc[i].dropna()
            if len(row) > 1 and all(isinstance(val, str) for val in row):
                header_row_idx = i
                break
                
        table_df = df.iloc[header_row_idx:].reset_index(drop=True)
        confidence = 0.95
        
        table = LogicalTable(
            sheet_name=sheet_name,
            start_row=header_row_idx,
            end_row=len(df)-1,
            dataframe=table_df,
            confidence=confidence
        )
        tables.append(table)
        
        return tables
