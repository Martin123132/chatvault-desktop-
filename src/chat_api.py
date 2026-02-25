# chat_api.py

import os
import subprocess
import sys
from typing import List, Dict, Any
import sqlite3
import base64
import requests
from openai.types.chat import ChatCompletionMessageParam
_MESSAGE_EXTRA_COLUMNS: bool | None = None


def _has_api_columns(con) -> bool:
    global _MESSAGE_EXTRA_COLUMNS
    if _MESSAGE_EXTRA_COLUMNS is not None:
        return _MESSAGE_EXTRA_COLUMNS

    cur = con.cursor()
    cur.execute("PRAGMA table_info(messages)")
    cols = {row[1] for row in cur.fetchall()}
    needed = {"api_request_json", "api_response_json", "request_hash"}
    _MESSAGE_EXTRA_COLUMNS = needed.issubset(cols)
    return _MESSAGE_EXTRA_COLUMNS
from dotenv import load_dotenv
from openai import OpenAI
from chatvault_db import get_project_system_prompt
from chatvault_db import get_project_model
from chatvault_db import list_project_notes, save_project_note, delete_project_note
from chatvault_db import list_workflows, create_workflow, delete_workflow, get_workflow, record_workflow_run
import json
import hashlib
import copy
from chatvault_db import get_messages, add_message
from tools_search import search_project_memory, web_search, fetch_url
from context_builder import build_context
from excel_tools import inspect_excel, modify_excel
from file_mod_tools import (
    modify_text_file,
    modify_csv_file,
    modify_docx_file,
    modify_pptx_file,
    modify_pdf_file,
    inspect_zip_file,
    extract_zip_file,
    create_zip_archive,
)
from doc_tools import inspect_pdf, inspect_docx, inspect_pptx
from table_tools import inspect_csv, transform_csv, generate_chart
from code_tools import inspect_code
from ai_files import save_ai_file

load_dotenv()

# Conservative defaults (sized below current model limits)
MAX_CONTEXT_TOKENS = 128000
RESERVE_COMPLETION_TOKENS = 6000

DEFAULT_MODEL = os.getenv("OPENAI_MODEL_DEFAULT", "gpt-5-mini")
FILE_ID_DESCRIPTION = "Message id with stored_path or absolute path under uploads"
ENCODING_DESCRIPTION = "Text encoding (default utf-8)"
PROJECT_ID_DESCRIPTION = "Target project id"
OUTPUT_MODE_DESCRIPTION = "Save beside original or overwrite"
SIDECAR_SUFFIX_DESCRIPTION = "Suffix for sidecar filename"

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
ANTHROPIC_MODEL_DEFAULT = os.getenv("ANTHROPIC_MODEL_DEFAULT")
GEMINI_MODEL_DEFAULT = os.getenv("GEMINI_MODEL_DEFAULT")

# Static allowlists per provider; filter by key presence
OPENAI_MODELS = [
    "openai:gpt-4o-mini",
    "openai:gpt-4o",
    "openai:gpt-4.1-mini",
    "openai:gpt-4.1",
]

ANTHROPIC_MODELS = [
    "anthropic:claude-3.5-sonnet-20241022",
    "anthropic:claude-3.5-haiku-20241022",
]

GEMINI_MODELS = [
    "gemini:gemini-1.5-flash-latest",
    "gemini:gemini-1.5-pro-latest",
]


def _parse_provider_model(model_id: str | None) -> tuple[str, str]:
    if not model_id:
        return "openai", DEFAULT_MODEL
    if ":" in model_id:
        provider, inner = model_id.split(":", 1)
        return provider.lower(), inner
    return "openai", model_id


def _available_models() -> list[str]:
    models: list[str] = []
    models.extend(OPENAI_MODELS)
    if ANTHROPIC_API_KEY:
        if ANTHROPIC_MODEL_DEFAULT:
            models.append(ANTHROPIC_MODEL_DEFAULT if ANTHROPIC_MODEL_DEFAULT.startswith("anthropic:") else f"anthropic:{ANTHROPIC_MODEL_DEFAULT}")
        models.extend(ANTHROPIC_MODELS)
    if GEMINI_API_KEY:
        if GEMINI_MODEL_DEFAULT:
            models.append(GEMINI_MODEL_DEFAULT if GEMINI_MODEL_DEFAULT.startswith("gemini:") else f"gemini:{GEMINI_MODEL_DEFAULT}")
        models.extend(GEMINI_MODELS)
    return models


def _render_messages_to_prompt(messages: list[ChatCompletionMessageParam]) -> str:
    parts: List[str] = []
    for m in messages:
        role = m.get("role", "user").upper()
        content = m.get("content", "")
        if isinstance(content, list):
            text_parts = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    text_parts.append(item.get("text", ""))
            content = "\n".join(text_parts)
        elif not isinstance(content, str):
            content = str(content)
        parts.append(f"{role}: {content}")
    return "\n\n".join(parts)

SEARCH_TOOL_DEF = {
    "type": "function",
    "function": {
        "name": "search_project_memory",
        "description": "Search previous conversations (scoped to current project if set, otherwise all) and return matching messages (truncated).",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "What to search for"
                }
            },
            "required": ["query"]
        }
    }
}

WEB_SEARCH_TOOL_DEF = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": "Perform a web search using SerpAPI (if configured) or DuckDuckGo HTML and return top results.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "max_results": {"type": "integer", "description": "Maximum results (1-10)"}
            },
            "required": ["query"]
        }
    }
}

FETCH_URL_TOOL_DEF = {
    "type": "function",
    "function": {
        "name": "fetch_url",
        "description": "Fetch a URL and return cleaned text content with metadata.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "HTTP or HTTPS URL to fetch"},
                "max_bytes": {"type": "integer", "description": "Optional byte cap (default 200k)"}
            },
            "required": ["url"]
        }
    }
}

EXCEL_INSPECT_TOOL_DEF = {
    "type": "function",
    "function": {
        "name": "inspect_excel",
        "description": "Inspect an uploaded Excel workbook (.xlsx/.xlsm). Returns sheet names, dimensions, and sampled cell contents or formulas.",
        "parameters": {
            "type": "object",
            "properties": {
                "file_id": {"type": "string", "description": FILE_ID_DESCRIPTION},
                "sheet": {"type": "string", "description": "Sheet name to inspect (defaults to first sheet)"},
                "range": {"type": "string", "description": "Optional A1-style range to inspect"},
                "mode": {"type": "string", "enum": ["values", "formulas", "both"], "description": "Return values, formulas, or both"},
                "max_rows": {"type": "integer", "description": "Row cap when no range is provided"},
                "max_cols": {"type": "integer", "description": "Column cap when no range is provided"},
                "max_cells": {"type": "integer", "description": "Cell cap to avoid huge payloads"}
            },
            "required": ["file_id"]
        }
    }
}

EXCEL_MODIFY_TOOL_DEF = {
    "type": "function",
    "function": {
        "name": "modify_excel",
        "description": "Apply cell edits to an Excel workbook and save a sidecar copy (or replace in place).",
        "parameters": {
            "type": "object",
            "properties": {
                "file_id": {"type": "string", "description": FILE_ID_DESCRIPTION},
                "edits": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "sheet": {"type": "string", "description": "Target sheet (defaults to first sheet)"},
                            "cell": {"type": "string", "description": "A1 cell (or range) to update"},
                            "range": {"type": "string", "description": "Alias for cell when applying to a range"},
                            "value": {"description": "Literal value to set (ignored when formula is provided)"},
                            "formula": {"type": "string", "description": "Formula to set (e.g., =SUM(A1:A3))"}
                        },
                        "required": ["cell"]
                    }
                },
                "output_mode": {"type": "string", "enum": ["sidecar", "replace"], "description": OUTPUT_MODE_DESCRIPTION},
                "output_suffix": {"type": "string", "description": SIDECAR_SUFFIX_DESCRIPTION},
                "create_sheets": {"type": "boolean", "description": "Create sheet when missing"}
            },
            "required": ["file_id", "edits"]
        }
    }
}

TEXT_MODIFY_TOOL_DEF = {
    "type": "function",
    "function": {
        "name": "modify_text_file",
        "description": "Modify a text or JSON file and save a sidecar (or replace). For JSON you can pass a shallow patch; for text pass full content.",
        "parameters": {
            "type": "object",
            "properties": {
                "file_id": {"type": "string", "description": FILE_ID_DESCRIPTION},
                "content": {"type": "string", "description": "Full text content to write (optional if json_patch provided)"},
                "json_patch": {"type": "object", "description": "Shallow JSON object merge; requires the file to be JSON"},
                "output_mode": {"type": "string", "enum": ["sidecar", "replace"], "description": OUTPUT_MODE_DESCRIPTION},
                "output_suffix": {"type": "string", "description": SIDECAR_SUFFIX_DESCRIPTION},
                "encoding": {"type": "string", "description": "Text encoding (default utf-8)"},
            },
            "required": ["file_id"],
        },
    },
}

CSV_MODIFY_TOOL_DEF = {
    "type": "function",
    "function": {
        "name": "modify_csv_file",
        "description": "Modify or append rows to a CSV/TSV and save a sidecar (or replace).",
        "parameters": {
            "type": "object",
            "properties": {
                "file_id": {"type": "string", "description": FILE_ID_DESCRIPTION},
                "rows": {"type": "array", "items": {"type": "array", "items": {}}, "description": "Full replacement rows (2D array)"},
                "append_rows": {"type": "array", "items": {"type": "array", "items": {}}, "description": "Rows to append"},
                "output_mode": {"type": "string", "enum": ["sidecar", "replace"], "description": OUTPUT_MODE_DESCRIPTION},
                "output_suffix": {"type": "string", "description": SIDECAR_SUFFIX_DESCRIPTION},
            },
            "required": ["file_id"],
        },
    },
}

DOCX_MODIFY_TOOL_DEF = {
    "type": "function",
    "function": {
        "name": "modify_docx_file",
        "description": "Append or replace paragraphs in a DOCX and save a sidecar (or replace).",
        "parameters": {
            "type": "object",
            "properties": {
                "file_id": {"type": "string", "description": FILE_ID_DESCRIPTION},
                "append_paragraphs": {"type": "array", "items": {"type": "string"}, "description": "Paragraphs to append"},
                "replace_paragraphs": {"type": "array", "items": {"type": "object", "properties": {"index": {"type": "integer"}, "text": {"type": "string"}}, "required": ["index", "text"]}, "description": "Replace specific paragraphs by index (0-based)"},
                "find_replace": {"type": "array", "items": {"type": "object", "properties": {"find": {"type": "string"}, "replace": {}}, "required": ["find", "replace"]}, "description": "Find/replace text within paragraphs"},
                "output_mode": {"type": "string", "enum": ["sidecar", "replace"], "description": OUTPUT_MODE_DESCRIPTION},
                "output_suffix": {"type": "string", "description": SIDECAR_SUFFIX_DESCRIPTION},
            },
            "required": ["file_id"],
        },
    },
}

PPTX_MODIFY_TOOL_DEF = {
    "type": "function",
    "function": {
        "name": "modify_pptx_file",
        "description": "Append or update slides in a PPTX and save a sidecar (or replace).",
        "parameters": {
            "type": "object",
            "properties": {
                "file_id": {"type": "string", "description": FILE_ID_DESCRIPTION},
                "add_slide": {"type": "boolean", "description": "Add a new slide (default true)"},
                "title": {"type": "string", "description": "Slide title for added/updated slide"},
                "body": {"type": "string", "description": "Slide body text for added/updated slide"},
                "replace_slides": {"type": "array", "items": {"type": "object", "properties": {"index": {"type": "integer"}, "title": {"type": "string"}, "body": {"type": "string"}}, "required": ["index"]}, "description": "Replace slide title/body by slide index (0-based)"},
                "shape_edits": {"type": "array", "items": {"type": "object", "properties": {"slide_index": {"type": "integer"}, "shape_index": {"type": "integer"}, "text": {}}, "required": ["slide_index", "text"]}, "description": "Update text of a shape on a slide (by slide and optional shape index)"},
                "output_mode": {"type": "string", "enum": ["sidecar", "replace"], "description": OUTPUT_MODE_DESCRIPTION},
                "output_suffix": {"type": "string", "description": SIDECAR_SUFFIX_DESCRIPTION},
            },
            "required": ["file_id"],
        },
    },
}

PDF_MODIFY_TOOL_DEF = {
    "type": "function",
    "function": {
        "name": "modify_pdf_file",
        "description": "Append pages or overlay text onto a PDF and save a sidecar (or replace). Requires PyPDF2 + reportlab installed.",
        "parameters": {
            "type": "object",
            "properties": {
                "file_id": {"type": "string", "description": FILE_ID_DESCRIPTION},
                "append_pdf_ids": {"type": "array", "items": {"type": "string"}, "description": "Additional PDFs to append (by file_id)"},
                "append_text_pages": {"type": "array", "items": {"type": "string"}, "description": "Create new pages from text (one entry per page)"},
                "overlay_texts": {"type": "array", "items": {"type": "object", "properties": {"page_index": {"type": "integer"}, "text": {"type": "string"}, "x": {"type": "number"}, "y": {"type": "number"}, "font_size": {"type": "integer"}}, "required": ["page_index", "text"]}, "description": "Overlay text on existing pages"},
                "output_mode": {"type": "string", "enum": ["sidecar", "replace"], "description": "Save beside original or overwrite"},
                "output_suffix": {"type": "string", "description": "Suffix for sidecar filename"},
            },
            "required": ["file_id"],
        },
    },
}

ZIP_INSPECT_TOOL_DEF = {
    "type": "function",
    "function": {
        "name": "inspect_zip",
        "description": "List entries inside a ZIP archive without extracting.",
        "parameters": {
            "type": "object",
            "properties": {
                "file_id": {"type": "string", "description": FILE_ID_DESCRIPTION},
                "max_entries": {"type": "integer", "description": "Optional cap on entries returned"},
            },
            "required": ["file_id"],
        },
    },
}

ZIP_EXTRACT_TOOL_DEF = {
    "type": "function",
    "function": {
        "name": "extract_zip_file",
        "description": "Extract entries from a ZIP archive into the uploads area and return paths to the files.",
        "parameters": {
            "type": "object",
            "properties": {
                "file_id": {"type": "string", "description": FILE_ID_DESCRIPTION},
                "members": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional list of members to extract (defaults to all)",
                },
                "output_suffix": {
                    "type": "string",
                    "description": "Suffix for the extraction folder (defaults to -unzipped)",
                },
            },
            "required": ["file_id"],
        },
    },
}

ZIP_CREATE_TOOL_DEF = {
    "type": "function",
    "function": {
        "name": "create_zip",
        "description": "Create a ZIP archive from provided file_ids and return the stored path.",
        "parameters": {
            "type": "object",
            "properties": {
                "file_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of file_ids (message ids or paths) to include",
                },
                "zip_filename": {"type": "string", "description": "Optional filename for the new ZIP"},
            },
            "required": ["file_ids"],
        },
    },
}

RUN_PYTHON_TOOL_DEF = {
    "type": "function",
    "function": {
        "name": "run_python",
        "description": "Execute a short Python snippet in a sandboxed subprocess (no filesystem). Returns stdout/stderr and exit code.",
        "parameters": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "Python code to run"},
                "timeout_seconds": {"type": "integer", "description": "Optional timeout (seconds, default 8)"},
            },
            "required": ["code"],
        },
    },
}

PDF_INSPECT_TOOL_DEF = {
    "type": "function",
    "function": {
        "name": "inspect_pdf",
        "description": "Read a PDF (text extraction per page, truncated for size).",
        "parameters": {
            "type": "object",
            "properties": {
                "file_id": {"type": "string", "description": FILE_ID_DESCRIPTION},
                "max_pages": {"type": "integer", "description": "Maximum pages to read"},
                "max_chars": {"type": "integer", "description": "Character cap per page"}
            },
            "required": ["file_id"]
        }
    }
}

DOCX_INSPECT_TOOL_DEF = {
    "type": "function",
    "function": {
        "name": "inspect_docx",
        "description": "Read a DOCX and return paragraphs with styles (truncated for size).",
        "parameters": {
            "type": "object",
            "properties": {
                "file_id": {"type": "string", "description": FILE_ID_DESCRIPTION},
                "max_paragraphs": {"type": "integer", "description": "Max paragraphs to return"},
                "max_chars": {"type": "integer", "description": "Character cap per paragraph"}
            },
            "required": ["file_id"]
        }
    }
}

PPTX_INSPECT_TOOL_DEF = {
    "type": "function",
    "function": {
        "name": "inspect_pptx",
        "description": "Read a PPTX and return slide text (truncated for size).",
        "parameters": {
            "type": "object",
            "properties": {
                "file_id": {"type": "string", "description": FILE_ID_DESCRIPTION},
                "max_slides": {"type": "integer", "description": "Maximum slides to read"},
                "max_chars": {"type": "integer", "description": "Character cap per slide"}
            },
            "required": ["file_id"]
        }
    }
}

CSV_INSPECT_TOOL_DEF = {
    "type": "function",
    "function": {
        "name": "inspect_csv",
        "description": "Inspect a CSV/TSV: detect delimiter, header, and return sampled rows.",
        "parameters": {
            "type": "object",
            "properties": {
                "file_id": {"type": "string", "description": FILE_ID_DESCRIPTION},
                "max_rows": {"type": "integer", "description": "Row sample cap"},
                "max_bytes": {"type": "integer", "description": "Byte cap for sniffing"},
                "delimiter": {"type": "string", "description": "Override delimiter (e.g., ',' or '\t')"},
                "has_header": {"type": "boolean", "description": "Force header detection"},
                "encoding": {"type": "string", "description": ENCODING_DESCRIPTION}
            },
            "required": ["file_id"]
        }
    }
}

CSV_TRANSFORM_TOOL_DEF = {
    "type": "function",
    "function": {
        "name": "transform_csv",
        "description": "Filter and project a CSV to a sidecar or replace in place.",
        "parameters": {
            "type": "object",
            "properties": {
                "file_id": {"type": "string", "description": FILE_ID_DESCRIPTION},
                "select_columns": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Columns to keep (by header name). Omit to keep all."
                },
                "filter_equals": {"type": "object", "description": "Exact-match filters by column name."},
                "filter_contains": {"type": "object", "description": "Substring filters by column name."},
                "limit_rows": {"type": "integer", "description": "Stop after this many matched rows"},
                "delimiter": {"type": "string", "description": "Override delimiter"},
                "encoding": {"type": "string", "description": ENCODING_DESCRIPTION},
                "output_mode": {"type": "string", "enum": ["sidecar", "replace"], "description": OUTPUT_MODE_DESCRIPTION},
                "output_suffix": {"type": "string", "description": SIDECAR_SUFFIX_DESCRIPTION}
            },
            "required": ["file_id"]
        }
    }
}

CHART_GENERATE_TOOL_DEF = {
    "type": "function",
    "function": {
        "name": "generate_chart",
        "description": "Generate a simple chart (bar/line) and return base64 PNG.",
        "parameters": {
            "type": "object",
            "properties": {
                "series": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "label": {"type": "string"},
                            "value": {}
                        },
                        "required": ["value"]
                    },
                    "description": "Data points (label + value)."
                },
                "kind": {"type": "string", "enum": ["bar", "line"], "description": "Chart type"},
                "title": {"type": "string", "description": "Optional chart title"},
                "width": {"type": "number", "description": "Figure width in inches"},
                "height": {"type": "number", "description": "Figure height in inches"}
            },
            "required": ["series"]
        }
    }
}

CODE_INSPECT_TOOL_DEF = {
    "type": "function",
    "function": {
        "name": "inspect_code",
        "description": "Read a code/text file with offset and byte cap (returns text or base64).",
        "parameters": {
            "type": "object",
            "properties": {
                "file_id": {"type": "string", "description": FILE_ID_DESCRIPTION},
                "offset": {"type": "integer", "description": "Start byte offset"},
                "max_bytes": {"type": "integer", "description": "Max bytes to read"},
                "as_base64": {"type": "boolean", "description": "Return base64 instead of text"},
                "encoding": {"type": "string", "description": ENCODING_DESCRIPTION}
            },
            "required": ["file_id"]
        }
    }
}

WORKFLOW_CREATE_TOOL_DEF = {
    "type": "function",
    "function": {
        "name": "create_workflow",
        "description": "Create a workflow definition (metadata only; manual run).",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Workflow name"},
                "description": {"type": "string", "description": "What the workflow does"},
                "cron": {"type": "string", "description": "Cron expression (metadata only)"},
                "enabled": {"type": "boolean", "description": "Whether workflow is enabled"},
                "payload": {"type": "object", "description": "Arbitrary JSON payload for downstream execution"}
            },
            "required": ["name"]
        }
    }
}

WORKFLOW_LIST_TOOL_DEF = {
    "type": "function",
    "function": {
        "name": "list_workflows",
        "description": "List workflow definitions (metadata only).",
        "parameters": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Maximum workflows to return"}
            }
        }
    }
}

WORKFLOW_DELETE_TOOL_DEF = {
    "type": "function",
    "function": {
        "name": "delete_workflow",
        "description": "Delete a workflow definition by id.",
        "parameters": {
            "type": "object",
            "properties": {
                "workflow_id": {"type": "integer", "description": "Workflow id"}
            },
            "required": ["workflow_id"]
        }
    }
}

WORKFLOW_RUN_TOOL_DEF = {
    "type": "function",
    "function": {
        "name": "run_workflow",
        "description": "Manually trigger a workflow and return its payload (no background scheduler).",
        "parameters": {
            "type": "object",
            "properties": {
                "workflow_id": {"type": "integer", "description": "Workflow id"},
                "next_run": {"type": "string", "description": "Optional next_run timestamp to store"}
            },
            "required": ["workflow_id"]
        }
    }
}

AI_WRITE_FILE_TOOL_DEF = {
    "type": "function",
    "function": {
        "name": "write_file",
        "description": "Create a file under a conversation and store it server-side (downloadable via existing file download endpoint).",
        "parameters": {
            "type": "object",
            "properties": {
                "conversation_id": {"type": "integer", "description": "Conversation id to attach the file to"},
                "filename": {"type": "string", "description": "Filename to save (extension required)"},
                "data_base64": {"type": "string", "description": "Base64-encoded file bytes"},
                "content_type": {"type": "string", "description": "MIME type (optional)"}
            },
            "required": ["conversation_id", "filename", "data_base64"]
        }
    }
}

PROJECT_NOTES_LIST_TOOL_DEF = {
    "type": "function",
    "function": {
        "name": "get_project_notes",
        "description": "List pinned project notes for grounding responses.",
        "parameters": {
            "type": "object",
            "properties": {
                "project_id": {"type": "integer", "description": PROJECT_ID_DESCRIPTION},
                "limit": {"type": "integer", "description": "Maximum notes to return"}
            },
            "required": ["project_id"]
        }
    }
}

PROJECT_NOTES_SAVE_TOOL_DEF = {
    "type": "function",
    "function": {
        "name": "save_project_note",
        "description": "Create or update a pinned project note (title + content).",
        "parameters": {
            "type": "object",
            "properties": {
                "project_id": {"type": "integer", "description": "Target project id"},
                "title": {"type": "string", "description": "Note title"},
                "content": {"type": "string", "description": "Note body"},
                "note_id": {"type": "integer", "description": "Existing note id to update (omit to create)"}
            },
            "required": ["project_id", "title", "content"]
        }
    }
}

PROJECT_NOTES_DELETE_TOOL_DEF = {
    "type": "function",
    "function": {
        "name": "delete_project_note",
        "description": "Delete a pinned project note by id.",
        "parameters": {
            "type": "object",
            "properties": {
                "project_id": {"type": "integer", "description":  PROJECT_ID_DESCRIPTION},
                "note_id": {"type": "integer", "description": "Note id to delete"}
            },
            "required": ["project_id", "note_id"]
        }
    }
}

def hash_request(payload: dict) -> str:
    """
    Deterministic hash of an API request payload.
    """
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _hydrate_fulltext(meta_json: str | None, content: str) -> str:
    if not meta_json:
        return content
    try:
        meta = json.loads(meta_json)
    except json.JSONDecodeError:
        return content
    full_text = meta.get("full_text")
    if isinstance(full_text, str) and full_text.strip():
        return full_text
    return content


def _get_openai_client():
    """Initializes and returns the OpenAI client."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not set")
    return OpenAI(api_key=api_key)


def _prepare_chat_messages(con, conversation_id, project_id, user_text) -> list[ChatCompletionMessageParam]:
    """Prepares messages for the API call."""
    add_message(
        con=con,
        conversation_id=conversation_id,
        source="api_chat",
        role="user",
        content=user_text
    )

    rows = get_messages(con, conversation_id, limit=2000)
    history: list[ChatCompletionMessageParam] = []
    for r in rows:
        role = r[1]
        if role not in ("user", "assistant", "system"):
            continue
        content = _hydrate_fulltext(r[4], r[3])
        history.append({"role": role, "content": content})  # type: ignore

    system_message: ChatCompletionMessageParam | None = None
    if project_id:
        sp = get_project_system_prompt(con, project_id)
        if sp.strip():
            system_message = {"role": "system", "content": sp.strip()}  # type: ignore

    return build_context(
        system_message=system_message,
        conversation_messages=history,
        max_tokens=MAX_CONTEXT_TOKENS,
        reserve_tokens=RESERVE_COMPLETION_TOKENS
    )


def _deserialize_tool_args(raw_args):
    if isinstance(raw_args, str):
        try:
            raw_args = json.loads(raw_args)
        except json.JSONDecodeError:
            return {}
    return raw_args if isinstance(raw_args, dict) else {}


def _safe_int(value):
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _safe_float(value):
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _safe_bool(value, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() not in ("false", "0", "no", "off", "")
    return bool(value)


def _truncate_serialized(serialized: str, max_len: int):
    return serialized if len(serialized) <= max_len else serialized[:max_len] + "... [truncated]"


def _build_tool_response(call, name: str, content: str):
    return {
        "role": "tool",
        "tool_call_id": call.id,
        "name": name,
        "content": content
    }

def _chat_with_anthropic(model: str, prompt: str, temperature: float = 0.7) -> str:
    if not ANTHROPIC_API_KEY:
        raise RuntimeError("Anthropic API key not configured")

    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    payload = {
        "model": model,
        "max_tokens": 800,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": max(0.0, min(float(temperature), 1.0)),
    }
    resp = requests.post("https://api.anthropic.com/v1/messages", headers=headers, json=payload, timeout=30)
    if resp.status_code != 200:
        raise RuntimeError(f"Anthropic error: {resp.status_code} {resp.text}")
    data = resp.json()
    content = data.get("content") or []
    if isinstance(content, list) and content:
        first = content[0]
        if isinstance(first, dict):
            return str(first.get("text", "")).strip()
    return str(data).strip()


def _chat_with_gemini(model: str, prompt: str, temperature: float = 0.7) -> str:
    if not GEMINI_API_KEY:
        raise RuntimeError("Gemini API key not configured")

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={GEMINI_API_KEY}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": max(0.0, min(float(temperature), 1.0))},
    }
    resp = requests.post(url, json=payload, timeout=30)
    if resp.status_code != 200:
        raise RuntimeError(f"Gemini error: {resp.status_code} {resp.text}")
    data = resp.json()
    candidates = data.get("candidates") or []
    if candidates:
        first = candidates[0]
        content = first.get("content", {}) if isinstance(first, dict) else {}
        parts = content.get("parts") if isinstance(content, dict) else None
        if parts:
            texts = [p.get("text", "") for p in parts if isinstance(p, dict)]
            return "\n".join(texts).strip()
    return str(data).strip()


def _chat_with_provider(provider: str, model: str, prompt: str, temperature: float = 0.7) -> str:
    if provider == "anthropic":
        return _chat_with_anthropic(model, prompt, temperature)
    if provider == "gemini":
        return _chat_with_gemini(model, prompt, temperature)
    raise RuntimeError(f"Unsupported provider: {provider}")


def _detect_council_agreement(transcript: list[dict[str, Any]], latest_round: int) -> bool:
    """Heuristic agreement detector using Jaccard overlap on latest round responses."""
    recent = [
        t for t in transcript
        if t.get("round") == latest_round and t.get("response")
    ]
    if len(recent) < 2:
        return False
    token_sets = []
    for t in recent:
        tokens = {tok for tok in str(t["response"]).lower().split() if len(tok) > 3}
        token_sets.append(tokens)
    if not token_sets:
        return False
    for i in range(len(token_sets)):
        for j in range(i + 1, len(token_sets)):
            a, b = token_sets[i], token_sets[j]
            if not a or not b:
                return False
            overlap = len(a & b) / len(a | b)
            if overlap < 0.35:
                return False
    return True


def _run_council_rounds(
    *,
    client: OpenAI,
    api_messages: list[ChatCompletionMessageParam],
    active_participants: list[str],
    temperature: float,
    max_rounds: int,
) -> tuple[list[dict[str, Any]], int, bool]:
    transcript: list[dict[str, Any]] = []
    rounds_run = 0
    agreed = False

    def build_prompt() -> str:
        transcript_text = "\n\n".join(
            [f"Round {t['round']} {t['participant']}: {t['response']}" for t in transcript]
        )
        prompt_text = _render_messages_to_prompt(api_messages)
        if transcript_text:
            prompt_text += "\n\nCouncil so far:\n" + transcript_text
        return prompt_text + "\n\nRespond concisely, move toward consensus, and avoid repetition."

    for round_idx in range(1, max_rounds + 1):
        rounds_run = round_idx
        for pid in active_participants:
            provider, base_model = _parse_provider_model(pid)
            try:
                prompt_text = build_prompt()

                if provider == "openai":
                    completion = client.chat.completions.create(
                        model=base_model,
                        messages=[
                            {"role": "system", "content": "You are a council member working toward a shared answer."},
                            {"role": "user", "content": prompt_text},
                        ],
                        temperature=temperature,
                    )
                    content = (completion.choices[0].message.content or "").strip()
                else:
                    content = _chat_with_provider(provider, base_model, prompt_text, temperature=temperature)
            except Exception as exc:  # pragma: no cover - defensive
                content = f"Error from {pid}: {exc}"

            transcript.append({
                "round": round_idx,
                "participant": pid,
                "provider": provider,
                "model": base_model,
                "response": content,
            })

        if _detect_council_agreement(transcript, round_idx):
            agreed = True
            break

    return transcript, rounds_run, agreed


def council_conversation(  # noqa: C901
    con,
    conversation_id: int,
    user_text: str,
    project_id: int | None = None,
    participants: list[str] | None = None,
    temperature: float = 0.7,
    max_rounds: int = 2,
) -> dict[str, Any]:
    client = _get_openai_client()
    api_messages = _prepare_chat_messages(con, conversation_id, project_id, user_text)

    active_participants = participants or _available_models()[:3]
    transcript, rounds_run, agreed = _run_council_rounds(
        client=client,
        api_messages=api_messages,
        active_participants=active_participants,
        temperature=temperature,
        max_rounds=max_rounds,
    )

    # Build consensus using the OpenAI default model
    consensus_prompt = "Draft a single, concise final answer reflecting consensus across these participants.\n\n"
    for entry in transcript:
        consensus_prompt += f"Round {entry['round']} {entry['participant']} says:\n{entry['response']}\n\n"

    consensus_messages: list[ChatCompletionMessageParam] = [
        {"role": "system", "content": "You are a mediator. Combine the inputs into one coherent answer."},
        {"role": "user", "content": consensus_prompt.strip()},
    ]

    consensus = ""
    try:
        completion = client.chat.completions.create(
            model=_parse_provider_model(DEFAULT_MODEL)[1],
            messages=consensus_messages,
            temperature=0.3,
        )
        consensus = (completion.choices[0].message.content or "").strip()
    except Exception as exc:  # pragma: no cover - defensive
        consensus = f"Consensus generation failed: {exc}"

    message_id = add_message(
        con=con,
        conversation_id=conversation_id,
        source="api_chat",
        role="assistant",
        content=consensus,
        meta={
            "replayable": False,
            "council": True,
            "participants": active_participants,
            "rounds_run": rounds_run,
            "agreed": agreed,
            "deliberation_log": transcript,
        },
    )

    return {
        "ok": True,
        "reply": consensus,
        "message_id": message_id,
        "participants": active_participants,
       "rounds_run": rounds_run,
        "agreed": agreed,
        "deliberation_log": transcript,
    }


def _handle_search_tool(call, args, con, project_id):
    query = args.get("query", "").strip()
    results = search_project_memory(con=con, query=query, project_id=project_id, limit=12)
    serialized = _truncate_serialized(json.dumps(results), 60000)
    return _build_tool_response(call, "search_project_memory", serialized)


def _handle_web_search_tool(call, args):
    query = args.get("query", "").strip()
    max_results_int = _safe_int(args.get("max_results"))
    results = web_search(query=query, max_results=max_results_int or 5)
    return _build_tool_response(call, "web_search", json.dumps(results))


def _handle_fetch_url_tool(call, args):
    url = args.get("url", "").strip()
    max_bytes_int = _safe_int(args.get("max_bytes"))
    serialized = _truncate_serialized(json.dumps(fetch_url(url=url, max_bytes=max_bytes_int)), 70000)
    return _build_tool_response(call, "fetch_url", serialized)


def _handle_inspect_excel_tool(call, args, con):
    try:
        result = inspect_excel(
            con=con,
            file_id=args.get("file_id", ""),
            sheet=args.get("sheet"),
            cell_range=args.get("range"),
            mode=args.get("mode", "values"),
            max_rows=_safe_int(args.get("max_rows")),
            max_cols=_safe_int(args.get("max_cols")),
            max_cells=_safe_int(args.get("max_cells")),
        )
    except Exception as exc:  # pragma: no cover - defensive
        result = {"error": str(exc)}
    serialized = _truncate_serialized(json.dumps(result, default=str), 60000)
    return _build_tool_response(call, "inspect_excel", serialized)


def _handle_modify_excel_tool(call, args, con):
    try:
        edits = args.get("edits") or []
        result = modify_excel(
            con=con,
            file_id=args.get("file_id", ""),
            edits=edits,
            output_mode=(args.get("output_mode") or "sidecar"),
            output_suffix=(args.get("output_suffix") or "-edited"),
            create_sheets=_safe_bool(args.get("create_sheets"), True),
        )
    except Exception as exc:  # pragma: no cover - defensive
        result = {"error": str(exc)}
    serialized = _truncate_serialized(json.dumps(result, default=str), 40000)
    return _build_tool_response(call, "modify_excel", serialized)


def _handle_modify_text_tool(call, args, con):
    try:
        result = modify_text_file(
            con=con,
            file_id=args.get("file_id", ""),
            content=args.get("content"),
            json_patch=args.get("json_patch"),
            output_mode=(args.get("output_mode") or "sidecar"),
            output_suffix=(args.get("output_suffix") or "-edited"),
            encoding=(args.get("encoding") or "utf-8"),
        )
    except Exception as exc:  # pragma: no cover - defensive
        result = {"error": str(exc)}
    serialized = _truncate_serialized(json.dumps(result, default=str), 40000)
    return _build_tool_response(call, "modify_text_file", serialized)


def _handle_modify_csv_tool(call, args, con):
    try:
        result = modify_csv_file(
            con=con,
            file_id=args.get("file_id", ""),
            rows=args.get("rows"),
            append_rows=args.get("append_rows"),
            output_mode=(args.get("output_mode") or "sidecar"),
            output_suffix=(args.get("output_suffix") or "-edited"),
        )
    except Exception as exc:  # pragma: no cover - defensive
        result = {"error": str(exc)}
    serialized = _truncate_serialized(json.dumps(result, default=str), 40000)
    return _build_tool_response(call, "modify_csv_file", serialized)


def _handle_modify_docx_tool(call, args, con):
    try:
        result = modify_docx_file(
            con=con,
            file_id=args.get("file_id", ""),
            append_paragraphs=args.get("append_paragraphs"),
            replace_paragraphs=args.get("replace_paragraphs"),
            find_replace=args.get("find_replace"),
            output_mode=(args.get("output_mode") or "sidecar"),
            output_suffix=(args.get("output_suffix") or "-edited"),
        )
    except Exception as exc:  # pragma: no cover - defensive
        result = {"error": str(exc)}
    serialized = _truncate_serialized(json.dumps(result, default=str), 40000)
    return _build_tool_response(call, "modify_docx_file", serialized)


def _handle_modify_pptx_tool(call, args, con):
    try:
        result = modify_pptx_file(
            con=con,
            file_id=args.get("file_id", ""),
            add_slide=_safe_bool(args.get("add_slide"), True),
            title=args.get("title"),
            body=args.get("body"),
            replace_slides=args.get("replace_slides"),
            shape_edits=args.get("shape_edits"),
            output_mode=(args.get("output_mode") or "sidecar"),
            output_suffix=(args.get("output_suffix") or "-edited"),
        )
    except Exception as exc:  # pragma: no cover - defensive
        result = {"error": str(exc)}
    serialized = _truncate_serialized(json.dumps(result, default=str), 40000)
    return _build_tool_response(call, "modify_pptx_file", serialized)


def _handle_modify_pdf_tool(call, args, con):
    try:
        result = modify_pdf_file(
            con=con,
            file_id=args.get("file_id", ""),
            append_pdf_ids=args.get("append_pdf_ids"),
            append_text_pages=args.get("append_text_pages"),
            overlay_texts=args.get("overlay_texts"),
            output_mode=(args.get("output_mode") or "sidecar"),
            output_suffix=(args.get("output_suffix") or "-edited"),
        )
    except Exception as exc:  # pragma: no cover - defensive
        result = {"error": str(exc)}
    serialized = _truncate_serialized(json.dumps(result, default=str), 40000)
    return _build_tool_response(call, "modify_pdf_file", serialized)


def _handle_inspect_zip_tool(call, args, con):
    try:
        result = inspect_zip_file(
            con=con,
            file_id=args.get("file_id", ""),
            max_entries=_safe_int(args.get("max_entries")),
        )
    except Exception as exc:  # pragma: no cover - defensive
        result = {"error": str(exc)}
    serialized = _truncate_serialized(json.dumps(result, default=str), 40000)
    return _build_tool_response(call, "inspect_zip", serialized)


def _handle_extract_zip_tool(call, args, con):
    try:
        result = extract_zip_file(
            con=con,
            file_id=args.get("file_id", ""),
            members=args.get("members"),
            output_suffix=(args.get("output_suffix") or "-unzipped"),
        )
    except Exception as exc:  # pragma: no cover - defensive
        result = {"error": str(exc)}
    serialized = _truncate_serialized(json.dumps(result, default=str), 40000)
    return _build_tool_response(call, "extract_zip_file", serialized)


def _handle_create_zip_tool(call, args, con):
    try:
        result = create_zip_archive(
            con=con,
            file_ids=args.get("file_ids") or [],
            zip_filename=args.get("zip_filename"),
        )
    except Exception as exc:  # pragma: no cover - defensive
        result = {"error": str(exc)}
    serialized = _truncate_serialized(json.dumps(result, default=str), 20000)
    return _build_tool_response(call, "create_zip", serialized)


def _handle_run_python_tool(call, args):
    code = args.get("code", "") or ""
    timeout = args.get("timeout_seconds")
    try:
        to = int(timeout) if timeout is not None else 8
    except Exception:
        to = 8

    try:
        proc = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            timeout=max(1, min(to, 20)),
        )
        result = {
            "ok": True,
            "returncode": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
        }
    except subprocess.TimeoutExpired as exc:
        result = {"error": f"timeout after {exc.timeout}s", "stdout": exc.stdout, "stderr": exc.stderr}
    except Exception as exc:  # pragma: no cover - defensive
        result = {"error": str(exc)}

    serialized = _truncate_serialized(json.dumps(result, default=str), 20000)
    return _build_tool_response(call, "run_python", serialized)


def _handle_inspect_pdf_tool(call, args, con):
    try:
        result = inspect_pdf(
            con=con,
            file_id=args.get("file_id", ""),
            max_pages=_safe_int(args.get("max_pages")),
            max_chars=_safe_int(args.get("max_chars")),
        )
    except Exception as exc:  # pragma: no cover - defensive
        result = {"error": str(exc)}
    serialized = _truncate_serialized(json.dumps(result, default=str), 60000)
    return _build_tool_response(call, "inspect_pdf", serialized)


def _handle_inspect_docx_tool(call, args, con):
    try:
        result = inspect_docx(
            con=con,
            file_id=args.get("file_id", ""),
            max_paragraphs=_safe_int(args.get("max_paragraphs")),
            max_chars=_safe_int(args.get("max_chars")),
        )
    except Exception as exc:  # pragma: no cover - defensive
        result = {"error": str(exc)}
    serialized = _truncate_serialized(json.dumps(result, default=str), 60000)
    return _build_tool_response(call, "inspect_docx", serialized)


def _handle_inspect_pptx_tool(call, args, con):
    try:
        result = inspect_pptx(
            con=con,
            file_id=args.get("file_id", ""),
            max_slides=_safe_int(args.get("max_slides")),
            max_chars=_safe_int(args.get("max_chars")),
        )
    except Exception as exc:  # pragma: no cover - defensive
        result = {"error": str(exc)}
    serialized = _truncate_serialized(json.dumps(result, default=str), 60000)
    return _build_tool_response(call, "inspect_pptx", serialized)


def _handle_get_project_notes_tool(call, args, con):
    try:
        pid = _safe_int(args.get("project_id"))
        limit = _safe_int(args.get("limit")) or 200
        if pid is None:
            raise ValueError("project_id is required")
        rows = list_project_notes(con, pid, limit=limit)
        payload = [
            {
                "id": r[0],
                "title": r[1],
                "content": r[2],
                "created_at": r[3],
                "updated_at": r[4],
            }
            for r in rows
        ]
        result = {"ok": True, "project_id": pid, "notes": payload}
    except Exception as exc:  # pragma: no cover - defensive
        result = {"error": str(exc)}
    serialized = _truncate_serialized(json.dumps(result, default=str), 40000)
    return _build_tool_response(call, "get_project_notes", serialized)


def _handle_save_project_note_tool(call, args, con):
    try:
        pid = _safe_int(args.get("project_id"))
        if pid is None:
            raise ValueError("project_id is required")
        note_id = _safe_int(args.get("note_id"))
        title = (args.get("title") or "").strip()
        content = args.get("content") or ""
        saved_id = save_project_note(con, project_id=pid, title=title, content=content, note_id=note_id)
        result = {"ok": True, "note_id": saved_id, "project_id": pid}
    except Exception as exc:  # pragma: no cover - defensive
        result = {"error": str(exc)}
    serialized = _truncate_serialized(json.dumps(result, default=str), 20000)
    return _build_tool_response(call, "save_project_note", serialized)


def _handle_delete_project_note_tool(call, args, con):
    try:
        pid = _safe_int(args.get("project_id"))
        note_id = _safe_int(args.get("note_id"))
        if pid is None or note_id is None:
            raise ValueError("project_id and note_id are required")
        delete_project_note(con, project_id=pid, note_id=note_id)
        result = {"ok": True, "project_id": pid, "note_id": note_id}
    except Exception as exc:  # pragma: no cover - defensive
        result = {"error": str(exc)}
    serialized = _truncate_serialized(json.dumps(result, default=str), 10000)
    return _build_tool_response(call, "delete_project_note", serialized)


def _handle_inspect_csv_tool(call, args, con):
    try:
        result = inspect_csv(
            con=con,
            file_id=args.get("file_id", ""),
            max_rows=_safe_int(args.get("max_rows")),
            max_bytes=_safe_int(args.get("max_bytes")),
            delimiter=args.get("delimiter"),
            has_header=args.get("has_header"),
            encoding=args.get("encoding"),
        )
    except Exception as exc:  # pragma: no cover - defensive
        result = {"error": str(exc)}
    serialized = _truncate_serialized(json.dumps(result, default=str), 60000)
    return _build_tool_response(call, "inspect_csv", serialized)


def _handle_transform_csv_tool(call, args, con):
    try:
        result = transform_csv(
            con=con,
            file_id=args.get("file_id", ""),
            select_columns=args.get("select_columns"),
            filter_equals=args.get("filter_equals"),
            filter_contains=args.get("filter_contains"),
            limit_rows=_safe_int(args.get("limit_rows")),
            delimiter=args.get("delimiter"),
            encoding=args.get("encoding"),
            output_mode=(args.get("output_mode") or "sidecar"),
            output_suffix=(args.get("output_suffix") or "-xform"),
        )
    except Exception as exc:  # pragma: no cover - defensive
        result = {"error": str(exc)}
    serialized = _truncate_serialized(json.dumps(result, default=str), 40000)
    return _build_tool_response(call, "transform_csv", serialized)


def _handle_generate_chart_tool(call, args):
    try:
        series = args.get("series") or []
        result = generate_chart(
            series=series,
            kind=(args.get("kind") or "bar"),
            title=args.get("title"),
            width=_safe_float(args.get("width")) or None,
            height=_safe_float(args.get("height")) or None,
        )
    except Exception as exc:  # pragma: no cover - defensive
        result = {"error": str(exc)}
    serialized = _truncate_serialized(json.dumps(result, default=str), 60000)
    return _build_tool_response(call, "generate_chart", serialized)


def _handle_inspect_code_tool(call, args, con):
    try:
        result = inspect_code(
            con=con,
            file_id=args.get("file_id", ""),
            offset=_safe_int(args.get("offset")) or 0,
            max_bytes=_safe_int(args.get("max_bytes")),
            as_base64=_safe_bool(args.get("as_base64"), False),
            encoding=args.get("encoding"),
        )
    except Exception as exc:  # pragma: no cover - defensive
        result = {"error": str(exc)}
    serialized = _truncate_serialized(json.dumps(result, default=str), 60000)
    return _build_tool_response(call, "inspect_code", serialized)


def _handle_create_workflow_tool(call, args, con):
    try:
        name = (args.get("name") or "").strip()
        description = args.get("description") or ""
        cron = (args.get("cron") or "").strip()
        enabled = _safe_bool(args.get("enabled"), True)
        payload = args.get("payload") or {}
        wf_id = create_workflow(
            con=con,
            name=name,
            description=description,
            cron=cron,
            enabled=enabled,
            payload=payload,
        )
        result = {"ok": True, "workflow_id": wf_id}
    except Exception as exc:  # pragma: no cover - defensive
        result = {"error": str(exc)}
    serialized = _truncate_serialized(json.dumps(result, default=str), 10000)
    return _build_tool_response(call, "create_workflow", serialized)


def _handle_list_workflows_tool(call, args, con):
    try:
        limit = _safe_int(args.get("limit")) or 200
        rows = list_workflows(con, limit=limit)
        payload = []
        for r in rows:
            payload.append({
                "id": r[0],
                "name": r[1],
                "description": r[2],
                "cron": r[3],
                "enabled": bool(r[4]),
                "payload": json.loads(r[5] or "{}"),
                "last_run": r[6],
                "next_run": r[7],
                "updated_at": r[8],
            })
        result = {"ok": True, "workflows": payload}
    except Exception as exc:  # pragma: no cover - defensive
        result = {"error": str(exc)}
    serialized = _truncate_serialized(json.dumps(result, default=str), 40000)
    return _build_tool_response(call, "list_workflows", serialized)


def _handle_delete_workflow_tool(call, args, con):
    try:
        wid = _safe_int(args.get("workflow_id"))
        if wid is None:
            raise ValueError("workflow_id is required")
        delete_workflow(con, workflow_id=wid)
        result = {"ok": True, "workflow_id": wid}
    except Exception as exc:  # pragma: no cover - defensive
        result = {"error": str(exc)}
    serialized = _truncate_serialized(json.dumps(result, default=str), 10000)
    return _build_tool_response(call, "delete_workflow", serialized)


def _handle_run_workflow_tool(call, args, con):
    try:
        wid = _safe_int(args.get("workflow_id"))
        if wid is None:
            raise ValueError("workflow_id is required")
        wf = get_workflow(con, wid)
        if not wf:
            raise ValueError("workflow not found")
        payload = json.loads(wf[5] or "{}")
        next_run = args.get("next_run")
        record_workflow_run(con, wid, next_run=next_run)
        result = {
            "ok": True,
            "workflow_id": wid,
            "name": wf[1],
            "description": wf[2],
            "cron": wf[3],
            "enabled": bool(wf[4]),
            "payload": payload,
            "last_run": wf[6],
            "next_run": next_run,
        }
    except Exception as exc:  # pragma: no cover - defensive
        result = {"error": str(exc)}
    serialized = _truncate_serialized(json.dumps(result, default=str), 20000)
    return _build_tool_response(call, "run_workflow", serialized)


def _handle_write_file_tool(call, args, con):
    try:
        conv_id = _safe_int(args.get("conversation_id"))
        filename = (args.get("filename") or "").strip()
        data_b64 = args.get("data_base64") or ""
        content_type = args.get("content_type")
        if conv_id is None:
            raise ValueError("conversation_id is required")
        if not filename:
            raise ValueError("filename is required")
        try:
            data_bytes = base64.b64decode(data_b64)
        except Exception:
            raise ValueError("data_base64 is not valid base64")
        result = save_ai_file(
            con=con,
            conversation_id=conv_id,
            filename=filename,
            data_bytes=data_bytes,
            content_type=content_type,
        )
    except Exception as exc:  # pragma: no cover - defensive
        result = {"error": str(exc)}
    serialized = _truncate_serialized(json.dumps(result, default=str), 20000)
    return _build_tool_response(call, "write_file", serialized)


def _handle_tool_call(call, con, project_id):
    """Handles a single tool call."""
    args = _deserialize_tool_args(call.function.arguments)
    handlers = {
        "search_project_memory": lambda: _handle_search_tool(call, args, con, project_id),
        "web_search": lambda: _handle_web_search_tool(call, args),
        "fetch_url": lambda: _handle_fetch_url_tool(call, args),
        "inspect_excel": lambda: _handle_inspect_excel_tool(call, args, con),
        "modify_excel": lambda: _handle_modify_excel_tool(call, args, con),
        "modify_text_file": lambda: _handle_modify_text_tool(call, args, con),
        "modify_csv_file": lambda: _handle_modify_csv_tool(call, args, con),
        "modify_docx_file": lambda: _handle_modify_docx_tool(call, args, con),
        "modify_pptx_file": lambda: _handle_modify_pptx_tool(call, args, con),
        "modify_pdf_file": lambda: _handle_modify_pdf_tool(call, args, con),
        "inspect_zip": lambda: _handle_inspect_zip_tool(call, args, con),
        "extract_zip_file": lambda: _handle_extract_zip_tool(call, args, con),
        "create_zip": lambda: _handle_create_zip_tool(call, args, con),
        "run_python": lambda: _handle_run_python_tool(call, args),
        "inspect_pdf": lambda: _handle_inspect_pdf_tool(call, args, con),
        "inspect_docx": lambda: _handle_inspect_docx_tool(call, args, con),
        "inspect_pptx": lambda: _handle_inspect_pptx_tool(call, args, con),
        "get_project_notes": lambda: _handle_get_project_notes_tool(call, args, con),
        "save_project_note": lambda: _handle_save_project_note_tool(call, args, con),
        "delete_project_note": lambda: _handle_delete_project_note_tool(call, args, con),
        "inspect_csv": lambda: _handle_inspect_csv_tool(call, args, con),
        "transform_csv": lambda: _handle_transform_csv_tool(call, args, con),
        "generate_chart": lambda: _handle_generate_chart_tool(call, args),
        "inspect_code": lambda: _handle_inspect_code_tool(call, args, con),
        "create_workflow": lambda: _handle_create_workflow_tool(call, args, con),
        "list_workflows": lambda: _handle_list_workflows_tool(call, args, con),
        "delete_workflow": lambda: _handle_delete_workflow_tool(call, args, con),
        "run_workflow": lambda: _handle_run_workflow_tool(call, args, con),
        "write_file": lambda: _handle_write_file_tool(call, args, con),
    }
    handler = handlers.get(call.function.name)
    return handler() if handler else None


def _execute_chat_loop(client, request_payload, con, project_id):
    """Executes the chat completion loop, handling tool calls."""
    while True:
        resp = client.chat.completions.create(**request_payload)
        msg = resp.choices[0].message

        if msg.tool_calls:
            # Preserve the assistant turn that requested tools so tool results have proper context.
            request_payload["messages"].append({
                "role": msg.role,
                "content": msg.content,
                "tool_calls": [tc.model_dump() for tc in msg.tool_calls],
            })

            for call in msg.tool_calls:
                tool_result = _handle_tool_call(call, con, project_id)
                if tool_result:
                    request_payload["messages"].append(tool_result)
            continue

        assistant_text = msg.content.strip() if msg.content else ""
        return resp, assistant_text


def _resolve_target_message_id(cur, conversation_id: int, message_id) -> int | None:
    if message_id is not None:
        return int(message_id)

    cur.execute(
        "SELECT MAX(id) FROM messages WHERE conversation_id=? AND role='assistant'",
        (conversation_id,)
    )
    row = cur.fetchone()
    if row and row[0] is not None:
        return int(row[0])
    return None


def _persist_request_metadata(cur, target_id: int, request_payload, response_json, request_hash: str) -> bool:
    try:
        cur.execute("SELECT meta_json FROM messages WHERE id=?", (target_id,))
        existing_meta_raw = cur.fetchone()
    except sqlite3.OperationalError:
        return False

    existing_meta = {}
    if existing_meta_raw and existing_meta_raw[0]:
        try:
            existing_meta = json.loads(existing_meta_raw[0])
        except json.JSONDecodeError:
            existing_meta = {}

    fallback_meta = {
        **existing_meta,
        "replayable": True,
        "api_request": request_payload,
        "api_response": response_json,
        "request_hash": request_hash
    }

    try:
        cur.execute(
            "UPDATE messages SET meta_json=? WHERE id=?",
            (json.dumps(fallback_meta), target_id)
        )
    except sqlite3.OperationalError:
        return False
    return True


def _update_api_columns(cur, target_id: int, request_payload, response_json, request_hash: str) -> bool:
    try:
        cur.execute(
            """
            UPDATE messages
            SET api_request_json=?, api_response_json=?, request_hash=?
            WHERE id = ?
            """,
            (
                json.dumps(request_payload),
                json.dumps(response_json),
                request_hash,
                target_id
            )
        )
    except sqlite3.OperationalError:
        return False
    return True


def _store_assistant_response(con, conversation_id, assistant_text, request_payload, final_resp):
    """Stores the assistant's response and associated metadata."""
    request_hash = hash_request(request_payload)
    response_json = final_resp.model_dump() if final_resp else {}

    message_id = add_message(
        con=con,
        conversation_id=conversation_id,
        source="api_chat",
        role="assistant",
        content=assistant_text,
        meta={"replayable": True}
    )

    cur = con.cursor()
    target_id = _resolve_target_message_id(cur, conversation_id, message_id)

    if target_id is None:
        con.commit()
        return

    if not _has_api_columns(con):
        if _persist_request_metadata(cur, target_id, request_payload, response_json, request_hash):
            con.commit()
        else:
            con.rollback()
        return

    if _update_api_columns(cur, target_id, request_payload, response_json, request_hash):
        con.commit()
        return

    if _persist_request_metadata(cur, target_id, request_payload, response_json, request_hash):
        con.commit()
    else:
        con.rollback()


def continue_conversation(
    con,
    conversation_id: int,
    user_text: str,
    project_id: int | None = None,
    model: str | None = None,
) -> str:
    client = _get_openai_client()

    api_messages = _prepare_chat_messages(con, conversation_id, project_id, user_text)
    chosen_model = model
    if not chosen_model and project_id:
        chosen_model = get_project_model(con, project_id)
    chosen_model = chosen_model or DEFAULT_MODEL

    provider, base_model = _parse_provider_model(chosen_model)

    tools = [SEARCH_TOOL_DEF]
    tools.extend([
        EXCEL_INSPECT_TOOL_DEF,
        EXCEL_MODIFY_TOOL_DEF,
        PDF_INSPECT_TOOL_DEF,
        DOCX_INSPECT_TOOL_DEF,
        PPTX_INSPECT_TOOL_DEF,
        PROJECT_NOTES_LIST_TOOL_DEF,
        PROJECT_NOTES_SAVE_TOOL_DEF,
        PROJECT_NOTES_DELETE_TOOL_DEF,
        CSV_INSPECT_TOOL_DEF,
        CSV_TRANSFORM_TOOL_DEF,
        CHART_GENERATE_TOOL_DEF,
        CODE_INSPECT_TOOL_DEF,
        WORKFLOW_CREATE_TOOL_DEF,
        WORKFLOW_LIST_TOOL_DEF,
        WORKFLOW_DELETE_TOOL_DEF,
        WORKFLOW_RUN_TOOL_DEF,
        AI_WRITE_FILE_TOOL_DEF,
        TEXT_MODIFY_TOOL_DEF,
        CSV_MODIFY_TOOL_DEF,
        DOCX_MODIFY_TOOL_DEF,
        PPTX_MODIFY_TOOL_DEF,
        PDF_MODIFY_TOOL_DEF,
        ZIP_INSPECT_TOOL_DEF,
        ZIP_EXTRACT_TOOL_DEF,
        ZIP_CREATE_TOOL_DEF,
        RUN_PYTHON_TOOL_DEF,
    ])
    tools.extend([WEB_SEARCH_TOOL_DEF, FETCH_URL_TOOL_DEF])

    if provider != "openai":
        # Run a tool-enabled OpenAI pass to gather context, then hand results to the target provider
        tool_messages = copy.deepcopy(api_messages)
        tool_payload = {
            "model": _parse_provider_model(DEFAULT_MODEL)[1],
            "messages": tool_messages,
            "tools": tools,
            "tool_choice": "auto",
        }
        try:
            _execute_chat_loop(client, tool_payload, con, project_id)
        except Exception:  # pragma: no cover - defensive
            # If tool pass fails, continue with original context
            tool_messages = api_messages
        prompt_text = _render_messages_to_prompt(tool_messages)
        assistant_text = _chat_with_provider(provider, base_model, prompt_text, temperature=0.7)
        add_message(
            con=con,
            conversation_id=conversation_id,
            source="api_chat",
            role="assistant",
            content=assistant_text,
            meta={
                "provider": provider,
                "model": base_model,
                "tool_runner": "openai",
                "tool_runner_model": _parse_provider_model(DEFAULT_MODEL)[1],
                "replayable": False,
            },
        )
        return assistant_text

    request_payload = {
        "model": base_model,
        "messages": api_messages,
        "tools": tools,
        "tool_choice": "auto"
    }

    final_resp, assistant_text = _execute_chat_loop(client, request_payload, con, project_id)

    _store_assistant_response(con, conversation_id, assistant_text, request_payload, final_resp)

    return assistant_text

