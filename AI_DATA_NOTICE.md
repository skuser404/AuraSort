# AI Data Notice (Document Insights)

Version: 1.0.0
Effective date: 10 November 2026
Owner: Sunil Kumar (GitHub: skuser404)

> **Note:** Template provided for convenience, not legal advice. Have a qualified lawyer review before relying on it.

> **The short version**
> - Document Insights is optional and off until you turn it on.
> - In local mode nothing leaves your computer.
> - In cloud mode you see what will be sent before every batch; numbers and IDs are masked and Confidential files are held back.
> - AuraSort cannot delete data held by a cloud provider; their privacy policy applies.
> - The AI only suggests. It never acts on your files. Check its output yourself.

## Local mode
- The engine (Ollama, LM Studio or llama.cpp) runs on your computer, and AuraSort only contacts it on `127.0.0.1`.
- AuraSort reads the text of the documents you choose (the first pages and characters only), finds confidential items
  with fixed rules, and asks the engine for a short description.
- Results live in memory and are cleared after the time you choose (30, 60 or 90 minutes, default 60) counted from when
  the batch finishes, when AuraSort closes, and immediately for a file that is moved or deleted. Nothing is written to
  disk, logs or History.

## Cloud mode
- **What is sent:** for each document, its file name and a limited excerpt of its text (at most a few thousand
  characters), with card, account, PAN, Aadhaar and similar numbers, e-mail addresses, phone numbers, tokens and
  passwords replaced by placeholders before sending. Each request is a single, stateless chat request with no stored
  conversation and no uploaded file.
- **What is never sent:** files flagged Confidential (unless you explicitly allow them for that one batch), file paths,
  other files, and the files themselves.
- **Confirmation:** before every batch you see how many files, roughly how many characters and pages will be sent, and
  you confirm or cancel.
- **API keys:** a key is kept in memory for the session by default. If you choose, it is stored in your system keychain
  (Windows Credential Manager, macOS Keychain or Linux Secret Service). It is never written to AuraSort's files, URLs or
  logs. "Withdraw consent / reset AI settings" removes it.
- **Deletion:** clearing results in AuraSort deletes only the local results. **AuraSort cannot delete data held by the
  provider.** The provider's own privacy policy applies to what you send.
- **DeepSeek:** DeepSeek's privacy policy states that data may be stored on servers in China. Check the current policy
  before using it. For banking, job, legal and medical documents, use local mode instead.

## Accuracy and limits
- Descriptions, document types and "likely junk" labels can be wrong or incomplete.
- Confidential detection is pattern- and rule-based. It can miss unusual formats and can flag harmless files.
- The AI never executes actions: it cannot open, move, delete or run anything, and text inside a document is treated as
  data, not as instructions. You review the results and decide.
