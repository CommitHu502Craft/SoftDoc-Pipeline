import os
import re
from typing import List, Dict, Set
from pathlib import Path

class DependencyValidator:
    """
    Validates and cleans dependencies in generated code.
    Ensures that only whitelisted standard libraries and seed dependencies are used.
    """

    def __init__(self, seeds_dir: str = "seeds"):
        self.seeds_dir = seeds_dir

        # Hardcoded Standard Library Whitelists
        self.STD_LIBS = {
            "python": {
                "os", "sys", "json", "datetime", "time", "typing", "pathlib", "random",
                "math", "re", "logging", "abc", "collections", "functools", "itertools",
                "hashlib", "uuid", "shutil", "enum", "threading", "asyncio", "copy"
            },
            "java": {
                "java.lang", "java.util", "java.io", "java.math", "java.time", "java.net",
                "java.text", "java.sql", "javax.servlet", "javax.persistence",
                "org.springframework", "lombok", "com.fasterxml.jackson", "org.slf4j"
            },
            "go": {
                "fmt", "os", "time", "strings", "strconv", "net/http", "encoding/json",
                "database/sql", "log", "math", "errors", "context", "sync"
            },
            "nodejs": {
                "fs", "path", "http", "https", "os", "util", "events", "crypto", "stream",
                "express", "mongoose", "body-parser", "cors", "dotenv"
            },
            "php": {
                "Illuminate", "App", "Carbon", "Exception", "DateTime", "json_encode", "count"
            }
        }

        # Comment syntax by language
        self.COMMENT_PREFIX = {
            "python": "# ",
            "java": "// ",
            "go": "// ",
            "nodejs": "// ",
            "php": "// "
        }

    def validate_and_clean(self, code: str, language: str, allowed_deps: list = None) -> str:
        """
        Scans code for imports, compares against whitelist, and removes/comments out illegal imports.
        """
        language = language.lower()
        if language == "node.js" or language == "node":
            language = "nodejs"

        if language not in self.STD_LIBS:
            return code

        # 1. Gather all allowed dependencies
        whitelist = set(self.STD_LIBS.get(language, []))

        # Add seed dependencies
        seed_deps = self._get_seed_dependencies(language)
        whitelist.update(seed_deps)

        # Add manually allowed deps
        if allowed_deps:
            whitelist.update(allowed_deps)

        # 2. Process code line by line to identify and filter imports
        lines = code.split('\n')
        cleaned_lines = []

        for line in lines:
            imports_in_line = self._extract_imports_from_line(line, language)

            if not imports_in_line:
                cleaned_lines.append(line)
                continue

            # Check if all imports in this line are valid
            is_valid = True
            invalid_deps = []

            for dep in imports_in_line:
                # Check if dep starts with any allowed prefix (mostly for Java/PHP namespaces)
                # or is an exact match (common for Python/Go/Node)
                if not self._is_allowed(dep, whitelist, language):
                    is_valid = False
                    invalid_deps.append(dep)

            if is_valid:
                cleaned_lines.append(line)
            else:
                # Comment out the illegal import
                comment = self.COMMENT_PREFIX.get(language, "// ")
                cleaned_lines.append(f"{comment} REMOVED ILLEGAL IMPORT: {line.strip()}  # Disallowed: {', '.join(invalid_deps)}")

        return '\n'.join(cleaned_lines)

    def _is_allowed(self, dep: str, whitelist: Set[str], language: str) -> bool:
        """Helper to check if a dependency is in the whitelist."""
        if dep in whitelist:
            return True

        # Check for partial matches (namespaces/packages)
        # For Java/PHP, 'java.util.List' is allowed if 'java.util' is in whitelist
        # For Python, 'os.path' is allowed if 'os' is in whitelist

        for allowed in whitelist:
            if language in ["java", "python", "php", "go"]:
                if dep.startswith(allowed + ".") or dep.startswith(allowed + "/"):
                     return True
                # Handle cases like "java.util" matching "java.util.List"
                if dep == allowed:
                    return True
            elif language == "nodejs":
                if dep == allowed:
                    return True
                if dep.startswith(allowed + "/"): # e.g. "fs/promises"
                    return True

        return False

    def _extract_imports(self, code: str, language: str) -> List[str]:
        """
        Extracts all imported dependencies from the given code string.
        """
        imports = []
        lines = code.split('\n')
        for line in lines:
            imports.extend(self._extract_imports_from_line(line, language))
        return list(set(imports))

    def _extract_imports_from_line(self, line: str, language: str) -> List[str]:
        """
        Extracts imports from a single line of code based on language syntax.
        """
        line = line.strip()
        imports = []

        if language == "python":
            # import x, y
            # from x import y
            import_match = re.match(r'^import\s+([\w\.,\s]+)', line)
            from_match = re.match(r'^from\s+([\w\.]+)\s+import', line)

            if import_match:
                # Handle "import os, sys"
                deps = import_match.group(1).split(',')
                for dep in deps:
                    imports.append(dep.strip().split('.')[0]) # Get root package
            elif from_match:
                imports.append(from_match.group(1).split('.')[0])

        elif language == "java":
            # import java.util.List;
            match = re.match(r'^import\s+([\w\.]+);', line)
            if match:
                full_class = match.group(1)
                # For validation, we often care about the package prefix.
                # But here we extract the full string found.
                imports.append(full_class)

        elif language == "go":
            # import "fmt"
            # import ( ... "fmt" ... ) - This function handles single line context mostly,
            # but usually Go files format imports line by line inside parentheses.
            # We look for quoted strings if the line looks like an import line.

            # Simple single line: import "fmt"
            single_match = re.match(r'^import\s+"([^"]+)"', line)
            if single_match:
                imports.append(single_match.group(1))
            else:
                # Inside import block: "fmt" or . "fmt" or name "fmt"
                # This requires context awareness if we strictly only want imports.
                # However, assuming this method is called on lines that ARE imports:
                # We can check if line is just a string in an import block context.
                # Since we process line by line stateless in validate_and_clean, handling Go import blocks is tricky.
                # For this implementation, we'll try to detect common patterns.

                # Check for just a quoted string (common inside import (...))
                # But we need to be careful not to pick up random strings in code.
                # validate_and_clean iterates lines.
                # To do this robustly for Go blocks, we might need a stateful parser or assume 'gofmt' style.
                # For now, we will regex for strings that look like package paths if indented/tabbed

                # Heuristic: If line is indented and contains a string, and looks like a package path
                block_match = re.search(r'"([\w\-/]+)"', line)
                if block_match:
                    # Very simple heuristic: valid go packages usually don't have spaces
                    imports.append(block_match.group(1))

        elif language == "nodejs":
            # const x = require('x');
            # import x from 'x';
            require_match = re.search(r'require\([\'"]([^\'"]+)[\'"]\)', line)
            import_match = re.search(r'import\s+.*\s+from\s+[\'"]([^\'"]+)[\'"]', line)

            if require_match:
                imports.append(require_match.group(1))
            if import_match:
                imports.append(import_match.group(1))

        elif language == "php":
            # use App\Models\User;
            match = re.match(r'^use\s+([\w\\]+);', line)
            if match:
                imports.append(match.group(1))

        return imports

    def _get_seed_dependencies(self, language: str) -> List[str]:
        """
        Scans the seeds/ directory for the given language to find existing valid imports.
        """
        seed_deps = set()
        lang_path = os.path.join(self.seeds_dir, language)

        # Map input language to folder name if different
        if language == "nodejs" and not os.path.exists(lang_path):
            if os.path.exists(os.path.join(self.seeds_dir, "node")):
                lang_path = os.path.join(self.seeds_dir, "node")

        if not os.path.exists(lang_path):
            return []

        # File extensions to look for
        extensions = {
            "python": ".py",
            "java": ".java",
            "go": ".go",
            "nodejs": [".js", ".ts"],
            "php": ".php"
        }

        exts = extensions.get(language)
        if not exts:
            return []
        if isinstance(exts, str):
            exts = [exts]

        for root, _, files in os.walk(lang_path):
            for file in files:
                if any(file.endswith(ext) for ext in exts):
                    file_path = os.path.join(root, file)
                    try:
                        with open(file_path, 'r', encoding='utf-8') as f:
                            content = f.read()
                            imports = self._extract_imports(content, language)
                            seed_deps.update(imports)
                    except Exception as e:
                        # Silently ignore read errors in seeds
                        continue

        return list(seed_deps)
