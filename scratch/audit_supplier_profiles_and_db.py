import os
import sys
sys.path.insert(0, os.path.abspath("."))
import json
import sqlite3

print("=== supplier_profiles.json ===")
if os.path.exists("supplier_profiles.json"):
    with open("supplier_profiles.json", "r", encoding="utf-8") as fp:
        sp = json.load(fp)
    print(f"Version: {sp.get('version')}, Total Suppliers: {len(sp.get('suppliers', {}))}")
    for supp_key, supp_data in sp.get("suppliers", {}).items():
        name = supp_data.get("supplier_name")
        gstin = supp_data.get("gstin")
        layouts = supp_data.get("layout_profiles", [])
        print(f"  Key: {supp_key:25s} | Name: {str(name):30s} | GSTIN: {str(gstin):18s} | Layouts: {len(layouts)}")
else:
    print("supplier_profiles.json NOT FOUND!")

print("\n=== templates.json ===")
if os.path.exists("templates.json"):
    with open("templates.json", "r", encoding="utf-8") as fp:
        tj = json.load(fp)
    print(f"Total templates: {len(tj)}")
    for k, v in tj.items():
        print(f"  Template Key: {k}")

print("\n=== SQLite Databases ===")
db_files = [f for f in os.listdir(".") if f.endswith(".db")]
print(f"Found {len(db_files)} SQLite databases: {db_files}")
for db in db_files:
    print(f"\n--- Database: {db} ---")
    try:
        conn = sqlite3.connect(db)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [r[0] for r in cursor.fetchall()]
        print(f"Tables: {tables}")
        if "suppliers" in tables:
            cursor.execute("SELECT id, supplier_key, supplier_name, gstin FROM suppliers;")
            suppliers = cursor.fetchall()
            print(f"Suppliers ({len(suppliers)}):")
            for s in suppliers:
                print(f"    {s}")
        if "invoice_documents" in tables:
            cursor.execute("SELECT id, original_filename, file_hash, supplier_key, extraction_decision, extraction_confidence FROM invoice_documents;")
            docs = cursor.fetchall()
            print(f"Invoice Documents ({len(docs)}):")
            for d in docs:
                print(f"    {d}")
        conn.close()
    except Exception as e:
        print(f"Error querying {db}: {e}")
