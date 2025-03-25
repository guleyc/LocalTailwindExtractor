# LocalTailwindExtractor

![GitHub](https://img.shields.io/github/license/guleyc/tailwind-tools)
![Python](https://img.shields.io/badge/python-3.6+-blue.svg)
![Last Commit](https://img.shields.io/github/last-commit/guleyc/tailwind-tools)

A powerful Python tool that scans PHP projects and extracts Tailwind CSS components for easy reuse and reference.

## 🚀 Features

- **Extracts Tailwind components** from PHP and HTML files
- **Categorizes components** by type (buttons, cards, forms, etc.)
- **Eliminates duplicates** using structural fingerprinting
- **Supports static analysis** of PHP files without execution
- **Optional PHP execution** to capture dynamically generated HTML
- **Multi-threaded processing** for faster extraction
- **Clean, organized output** in an easy-to-reference format

## 📋 Requirements

- Python 3.6 or higher
- BeautifulSoup4 library
- (Optional) PHP CLI for dynamic content extraction

## 🔧 Installation

1. Clone this repository:
   ```bash
   git clone https://github.com/guleyc/tailwind-tools.git
   cd tailwind-tools
