import pandas as pd
import io

def generate_sample_excel():
    # 1. Define HRMS Directory sheet data
    hrms_data = {
        "Employee ID": ["EMP_Alice", "EMP_Bob", "EMP_Charlie"],
        "Employee Name": ["Alice Vance", "Bob Smith", "Charlie Brown"],
        "Department": ["Operations", "Operations", "Engineering"],
        "Manager": ["Sarah Jenkins", "Sarah Jenkins", "Sarah Jenkins"],
        "Salary Grade": ["Grade 8", "Grade 7", "Grade 9"],
        "Salary": [85000, 72000, 98000]
    }
    df_hrms = pd.DataFrame(hrms_data)

    # 2. Define Logistics Tracker sheet data
    logistics_data = {
        "Shipment ID": ["SHIP_888", "SHIP_999"],
        "Product": ["Microchips", "Solar Panels"],
        "Origin": ["Taiwan", "China"],
        "Destination": ["USA", "Japan"],
        "Carrier": ["OceanCargo", "AirLogistics"]
    }
    df_logistics = pd.DataFrame(logistics_data)

    # 3. Write both dataframes to a single Excel file with multiple sheets
    output_path = "sample_enterprise_ontology.xlsx"
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        df_hrms.to_excel(writer, sheet_name="HRMS_Directory", index=False)
        df_logistics.to_excel(writer, sheet_name="Logistics_Tracker", index=False)

    print(f"Success! Sample Excel file generated at: {output_path}")

if __name__ == "__main__":
    generate_sample_excel()
