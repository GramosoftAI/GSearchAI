import asyncio
import traceback
from app.core.pdf_extractor import PDFExtractor
from app.core.adaptive_chunker import PDFStructureParser
from app.modules.rag.file_router.adapters import parse_pdf_structure

async def run():
    try:
        file_path = r"C:\Users\hp\Desktop\GSOFT\RAG\table (1).pdf"
        
        with open(file_path, "rb") as f:
            pdf_bytes = f.read()
            
        print("Running PDFExtractor.extract()...")
        text = await PDFExtractor.extract(pdf_bytes, filename="table (1).pdf")
        
        print("\n--- RAW PDFExtractor OUTPUT (first 500 chars) ---")
        print(text[:500] + "..." if len(text) > 500 else text)
        
        print("\n--- Running PDFStructureParser ---")
        parser = PDFStructureParser()
        blocks = parser.parse(text)
        
        if not blocks:
            print("No structured blocks found.")
        else:
            print(f"Found {len(blocks)} blocks.")
            for i, b in enumerate(blocks[:5]):
                print(f"Block {i}: Type={b.get('type')}, Heading={b.get('heading')}")
                btext = b.get("text", "")
                print(f"  Text: {repr(btext[:100])}...")
                
        if blocks:
            print("\n--- ADAPTER OUTPUT ---")
            sections = parse_pdf_structure(blocks)
            for i, s in enumerate(sections[:5]):
                print(f"Section {i}: Kind={s.get('kind')}, Title={s.get('title')}")
                stext = s.get("text", "")
                print(f"  Text: {repr(stext[:100])}...")
            
    except Exception as e:
        print(f"Error: {e}")
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(run())
