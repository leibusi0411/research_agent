# Use pypdf for Web PDF text extraction

Web Research will use `pypdf` to extract text from PDFs downloaded through `web.download_pdf` in v1. Extracted text is saved as a Web Source Snapshot task artifact and summarized into Findings by ResearchExecutor. V1 only targets basic PDF text extraction; complex layout reconstruction, table extraction, OCR, and high-fidelity rendering are deferred.
