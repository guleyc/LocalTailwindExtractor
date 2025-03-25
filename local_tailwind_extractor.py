#!/usr/bin/env python3
import os
import re
import hashlib
import argparse
import subprocess
import threading
import tempfile
import time
import sys
from collections import defaultdict
from bs4 import BeautifulSoup, Comment
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

class LocalTailwindExtractor:
    def __init__(self, project_dir, output_file="tailwind_components.txt", 
                 execute_php=False, php_path="php", max_threads=4, verbose=True):
        """
        Initialize the extractor to find Tailwind components in a local project directory.
        
        Args:
            project_dir (str): Path to the local project directory
            output_file (str): File to save extracted Tailwind components
            execute_php (bool): Whether to also execute PHP files to extract dynamic content
            php_path (str): Path to PHP executable for execution
            max_threads (int): Maximum number of threads for processing
            verbose (bool): Whether to print detailed progress information
        """
        self.project_dir = os.path.abspath(project_dir)
        self.output_file = output_file
        self.execute_php = execute_php  # Varsayılan olarak False yaptım
        self.php_path = php_path
        self.max_threads = max_threads
        self.verbose = verbose
        
        # Check if the project directory exists
        if not os.path.exists(self.project_dir):
            print(f"Error: Project directory {self.project_dir} does not exist!")
            sys.exit(1)
        
        # For storing unique HTML elements
        self.element_hashes = set()
        self.element_groups = defaultdict(list)
        
        # Temporary directory for PHP execution
        self.temp_dir = tempfile.mkdtemp(prefix="tailwind_extract_") if self.execute_php else None
        
        # For tracking statistics
        self.stats = {
            'files_scanned': 0,
            'php_files_found': 0,
            'php_files_executed': 0,
            'html_files_found': 0,
            'elements_found': 0,
            'unique_elements': 0,
            'duplicate_elements': 0,
            'execution_errors': 0
        }
        
        # Threading locks
        self.stats_lock = threading.Lock()
        self.hash_lock = threading.Lock()
        self.print_lock = threading.Lock()  # For synchronized printing
        
        # PHP patterns to extract HTML
        self.php_echo_pattern = re.compile(r'echo\s+[\'"](.+?)[\'"];', re.DOTALL)
        self.php_html_pattern = re.compile(r'<\?php.*?\?>|<\?=.*?\?>', re.DOTALL)
        
        # User info
        self.current_date = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
        self.current_user = os.environ.get('USERNAME', os.environ.get('USER', 'current_user'))
        
        # Check if PHP is available if execution is requested
        if self.execute_php:
            try:
                subprocess.run([self.php_path, '--version'], 
                              stdout=subprocess.PIPE, 
                              stderr=subprocess.PIPE, 
                              timeout=5)
            except (subprocess.SubprocessError, FileNotFoundError):
                print(f"Warning: PHP executable not found at '{self.php_path}'. PHP execution will be disabled.")
                self.execute_php = False
    
    def cleanup(self):
        """Clean up temporary files."""
        if self.temp_dir and os.path.exists(self.temp_dir):
            import shutil
            try:
                shutil.rmtree(self.temp_dir)
                if self.verbose:
                    print(f"Cleaned up temporary directory: {self.temp_dir}")
            except Exception as e:
                print(f"Warning: Failed to clean up temporary directory: {e}")
    
    def find_php_files(self):
        """Find all PHP and HTML files in the project directory."""
        php_files = []
        html_files = []
        
        if self.verbose:
            print(f"Scanning directory: {self.project_dir}")
        
        # Folders to skip
        skip_folders = ['node_modules', 'vendor', 'uploads', 'cache', '.git', 'log', 'logs']
        
        for root, dirs, files in os.walk(self.project_dir):
            # Skip certain directories
            dirs[:] = [d for d in dirs if d not in skip_folders and not d.startswith('.')]
            
            for file in files:
                file_path = os.path.join(root, file)
                
                # Skip files over 5MB or hidden files
                try:
                    if (os.path.getsize(file_path) > 5 * 1024 * 1024 or 
                        file.startswith('.')):
                        continue
                except (OSError, FileNotFoundError):
                    continue
                
                if file.endswith('.php'):
                    php_files.append(file_path)
                    with self.stats_lock:
                        self.stats['php_files_found'] += 1
                        
                elif file.endswith(('.html', '.htm', '.tpl')):
                    html_files.append(file_path)
                    with self.stats_lock:
                        self.stats['html_files_found'] += 1
                
                with self.stats_lock:
                    self.stats['files_scanned'] += 1
        
        if self.verbose:
            print(f"Found {len(php_files)} PHP files and {len(html_files)} HTML files")
        
        return php_files, html_files
    
    def extract_html_from_php_static(self, php_file):
        """Extract HTML from PHP file through static analysis."""
        try:
            with open(php_file, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            
            # Replace PHP blocks with placeholders to preserve surrounding HTML
            content_without_php = self.php_html_pattern.sub('', content)
            
            # Also try to extract HTML from echo statements
            echo_html = ' '.join(self.php_echo_pattern.findall(content))
            
            # Combine both sources
            combined_html = content_without_php + " " + echo_html
            
            return combined_html
        except Exception as e:
            with self.print_lock:
                if self.verbose:
                    print(f"Error analyzing {php_file}: {str(e)}")
            return ""
    
    def execute_php_file(self, php_file):
        """Execute a PHP file and return its HTML output."""
        if not self.execute_php:
            return ""
            
        try:
            # Check if the file exists
            if not os.path.exists(php_file):
                with self.stats_lock:
                    self.stats['execution_errors'] += 1
                with self.print_lock:
                    print(f"Error: PHP file not found: {php_file}")
                return ""
            
            # Basic execution with proper environment
            result = subprocess.run(
                [self.php_path, php_file],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=5,  # Limit execution time to prevent hangups
                env={
                    **os.environ,
                    'REQUEST_URI': '/',
                    'SCRIPT_NAME': os.path.basename(php_file),
                    'DOCUMENT_ROOT': os.path.dirname(php_file),
                    'SERVER_NAME': 'localhost',
                    'HTTP_HOST': 'localhost'
                }
            )
            
            if result.returncode == 0:
                with self.stats_lock:
                    self.stats['php_files_executed'] += 1
                return result.stdout
            else:
                with self.stats_lock:
                    self.stats['execution_errors'] += 1
                with self.print_lock:
                    if self.verbose:
                        print(f"Error executing {php_file}: {result.stderr}")
                return ""
                
        except Exception as e:
            with self.stats_lock:
                self.stats['execution_errors'] += 1
            with self.print_lock:
                if self.verbose:
                    print(f"Failed to execute {php_file}: {str(e)}")
            return ""
    
    def hash_element(self, element):
        """Create a hash of an element based on its structure and classes."""
        # Get element name
        element_type = element.name
        
        # Skip non-element nodes
        if not element_type:
            return None
            
        # Get classes (important for Tailwind)
        classes = element.get('class', [])
        if isinstance(classes, list):
            class_str = ' '.join(sorted(classes))
        else:
            class_str = str(classes)
        
        # Create a simplified structure for checking similarity
        structure = f"{element_type}:{class_str}"
        
        # For complex elements, include more structure details
        if element_type in ['div', 'section', 'form', 'nav', 'header', 'footer', 'table']:
            # Include direct children element types
            children = [child.name for child in element.find_all(recursive=False) if child.name]
            structure += ":" + ",".join(sorted(children))
        
        # Hash the structure string
        return hashlib.md5(structure.encode()).hexdigest()
    
    def clean_element(self, element):
        """Clean an element to reduce size and remove unnecessary parts."""
        # Create a copy to avoid modifying the original
        element_copy = BeautifulSoup(str(element), 'html.parser')
        
        # Remove comments
        for comment in element_copy.find_all(text=lambda text: isinstance(text, Comment)):
            comment.extract()
        
        # Remove script and style contents (keep the tags for structure)
        for tag in element_copy.find_all(['script', 'style']):
            if tag.string:
                tag.string = ""
        
        # Remove most attributes except class, id, and a few others
        for tag in element_copy.find_all(True):
            attrs_to_keep = ['class', 'id', 'type', 'placeholder', 'href', 'src', 'alt']
            attrs_to_remove = [attr for attr in tag.attrs if attr not in attrs_to_keep]
            
            for attr in attrs_to_remove:
                del tag[attr]
        
        # Simplify text content for large text blocks
        for tag in element_copy.find_all(text=True):
            if tag.parent.name not in ['script', 'style'] and len(tag.strip()) > 100:
                tag.replace_with(tag[:100] + "...")
        
        return element_copy
    
    def classify_element(self, element):
        """Classify the element by its likely purpose for organization."""
        element_type = element.name
        classes = element.get('class', [])
        if isinstance(classes, str):
            classes = classes.split()
        
        # Check element classes and structure for classification
        class_text = ' '.join(classes).lower() if classes else ""
        
        if element_type == 'button' or 'btn' in class_text or 'button' in class_text:
            return 'buttons'
        elif element_type == 'form' or element.find('form'):
            return 'forms'
        elif element_type == 'header' or 'header' in class_text or element.find('h1'):
            return 'headers'
        elif element_type == 'nav' or 'nav' in class_text or 'navbar' in class_text or 'menu' in class_text:
            return 'navbars'
        elif element_type == 'table' or element.find('table'):
            return 'tables'
        elif 'card' in class_text or (element_type == 'div' and element.find('img') and len(element.find_all('div')) > 1):
            return 'cards'
        elif 'container' in class_text or 'wrapper' in class_text:
            return 'containers'
        elif 'grid' in class_text or 'row' in class_text or 'flex' in class_text:
            return 'grids'
        elif element_type in ['input', 'select', 'textarea'] or element.find(['input', 'select', 'textarea']):
            return 'inputs'
        elif element_type == 'footer' or 'footer' in class_text:
            return 'footers'
        elif element_type == 'section' or 'section' in class_text:
            return 'sections'
        elif element_type == 'a' or element.find('a'):
            return 'links'
        else:
            return 'other'
    
    def extract_elements_from_html(self, html_content, source_file):
        """Extract Tailwind components from HTML content."""
        if not html_content or html_content.strip() == "":
            return 0
            
        try:
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # Count total elements found
            total_found = 0
            
            # Find significant elements that might be Tailwind components
            significant_elements = []
            
            # Look for elements with Tailwind classes
            for tag in soup.find_all(True, class_=True):
                classes = tag.get('class')
                if isinstance(classes, list):
                    class_str = ' '.join(classes)
                else:
                    class_str = str(classes)
                
                # If it has Tailwind-like classes
                if re.search(r'(^|\s)(bg-|text-|p-|m-|flex|grid|rounded|shadow|border|hover:|focus:)', class_str):
                    significant_elements.append(tag)
                    total_found += 1
            
            # Also look for common component patterns even without obvious Tailwind classes
            for component_type in ['button', 'card', 'nav', 'header', 'footer', 'form']:
                for tag in soup.find_all([component_type, 'div', 'section']):
                    # Skip tags we already added
                    if tag in significant_elements:
                        continue
                        
                    # Check if it seems like a component by class name
                    classes = tag.get('class', [])
                    if isinstance(classes, list):
                        class_str = ' '.join(classes)
                    else:
                        class_str = str(classes)
                    
                    if component_type in class_str.lower():
                        significant_elements.append(tag)
                        total_found += 1
            
            # Process each significant element
            for element in significant_elements:
                # Get a hash of the element
                element_hash = self.hash_element(element)
                
                if not element_hash:
                    continue
                    
                # Use a lock to prevent race conditions
                with self.hash_lock:
                    if element_hash not in self.element_hashes:
                        # This is a unique element
                        self.element_hashes.add(element_hash)
                        
                        # Clean and optimize the element
                        cleaned_element = self.clean_element(element)
                        
                        # Classify and store the element
                        category = self.classify_element(element)
                        self.element_groups[category].append((cleaned_element, source_file))
                        
                        with self.stats_lock:
                            self.stats['unique_elements'] += 1
                    else:
                        with self.stats_lock:
                            self.stats['duplicate_elements'] += 1
            
            with self.stats_lock:
                self.stats['elements_found'] += total_found
            
            return total_found
            
        except Exception as e:
            with self.print_lock:
                if self.verbose:
                    print(f"Error extracting elements from {source_file}: {str(e)}")
            return 0
    
    def process_file(self, file_path):
        """Process a single file (PHP or HTML)."""
        try:
            if file_path.endswith('.php'):
                # For PHP files, try both static analysis and execution
                html_from_static = self.extract_html_from_php_static(file_path)
                elements_from_static = self.extract_elements_from_html(html_from_static, file_path)
                
                # If enabled, also try executing the PHP
                elements_from_execution = 0
                if self.execute_php:
                    html_from_execution = self.execute_php_file(file_path)
                    elements_from_execution = self.extract_elements_from_html(html_from_execution, file_path)
                    
                    if elements_from_execution > 0:
                        with self.print_lock:
                            if self.verbose:
                                print(f"Found {elements_from_execution} elements from executing {os.path.relpath(file_path, self.project_dir)}")
                
                if elements_from_static > 0:
                    with self.print_lock:
                        if self.verbose:
                            print(f"Found {elements_from_static} elements from analyzing {os.path.relpath(file_path, self.project_dir)}")
                    
            else:
                # For HTML files, just extract elements directly
                try:
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        html_content = f.read()
                    
                    elements_found = self.extract_elements_from_html(html_content, file_path)
                    
                    if elements_found > 0:
                        with self.print_lock:
                            if self.verbose:
                                print(f"Found {elements_found} elements from {os.path.relpath(file_path, self.project_dir)}")
                        
                except Exception as e:
                    with self.print_lock:
                        if self.verbose:
                            print(f"Error processing {file_path}: {str(e)}")
                            
        except Exception as e:
            with self.print_lock:
                if self.verbose:
                    print(f"Error processing file {file_path}: {str(e)}")
    
    def save_unique_elements(self):
        """Save all unique elements to the output file."""
        try:
            with open(self.output_file, 'w', encoding='utf-8') as f:
                # Write summary header
                f.write(f"TAILWIND COMPONENTS FROM {os.path.basename(self.project_dir)}\n")
                f.write(f"=" * 60 + "\n\n")
                f.write(f"Extraction Date: {self.current_date}\n")
                f.write(f"Generated by: {self.current_user}\n\n")
                f.write(f"Files scanned: {self.stats['files_scanned']}\n")
                f.write(f"PHP files found: {self.stats['php_files_found']}\n")
                f.write(f"PHP files executed: {self.stats['php_files_executed']}\n")
                f.write(f"HTML files found: {self.stats['html_files_found']}\n")
                f.write(f"Total elements found: {self.stats['elements_found']}\n")
                f.write(f"Unique elements: {self.stats['unique_elements']}\n")
                f.write(f"Duplicate elements: {self.stats['duplicate_elements']}\n\n")
                
                if self.stats['execution_errors'] > 0:
                    f.write(f"Note: {self.stats['execution_errors']} PHP execution errors occurred during processing.\n\n")
                
                # Write each category
                for category, elements in self.element_groups.items():
                    if elements:
                        # Format category name
                        display_name = category.replace('_', ' ').title()
                        f.write(f"\n{display_name.upper()} ({len(elements)} elements)\n")
                        f.write("-" * 60 + "\n\n")
                        
                        # Write each element
                        for i, (element, source_file) in enumerate(elements):
                            element_html = str(element)
                            rel_path = os.path.relpath(source_file, self.project_dir)
                            
                            f.write(f"Element #{i+1} from {rel_path}\n")
                            f.write("```html\n")
                            f.write(element_html + "\n")
                            f.write("```\n\n")
                            
            return True
        except Exception as e:
            print(f"Error saving output file: {str(e)}")
            return False
    
    def extract(self):
        """Run the extraction process on the project directory."""
        start_time = time.time()
        
        try:
            print(f"Starting Tailwind component extraction from: {self.project_dir}")
            print(f"Output will be saved to: {self.output_file}")
            print(f"PHP execution is {'enabled' if self.execute_php else 'disabled'}")
            
            # Find all PHP and HTML files
            php_files, html_files = self.find_php_files()
            
            # Process all files using a thread pool
            with ThreadPoolExecutor(max_workers=self.max_threads) as executor:
                # Process PHP files first (they're likely to contain more components)
                futures = [executor.submit(self.process_file, file) for file in php_files]
                
                # Then process HTML files
                futures.extend([executor.submit(self.process_file, file) for file in html_files])
                
                # Wait for all files to be processed
                for future in futures:
                    future.result()
            
            # Save all unique elements
            if self.save_unique_elements():
                print(f"Successfully saved extracted components to {os.path.abspath(self.output_file)}")
            
            # Print summary
            elapsed_time = time.time() - start_time
            print("\nExtraction complete!")
            print(f"Processed {self.stats['files_scanned']} files in {elapsed_time:.1f} seconds")
            print(f"Found {self.stats['elements_found']} total elements")
            print(f"Saved {self.stats['unique_elements']} unique elements, ignored {self.stats['duplicate_elements']} duplicates")
            
            if self.stats['execution_errors'] > 0:
                print(f"Note: {self.stats['execution_errors']} PHP execution errors occurred.")
            
            # Print category breakdown
            print("\nElements by category:")
            for category, elements in self.element_groups.items():
                if elements:
                    print(f"  - {category.replace('_', ' ').title()}: {len(elements)}")
            
            print(f"\nComponents saved to: {os.path.abspath(self.output_file)}")
            
        finally:
            # Always clean up
            self.cleanup()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Extract Tailwind components from local PHP/HTML project files.')
    parser.add_argument('project_dir', help='Path to the project directory (e.g., ~/Desktop/myscript)')
    parser.add_argument('--output', '-o', default='tailwind_components.txt', help='Output file name')
    parser.add_argument('--execute-php', '-e', action='store_true', help='Enable PHP execution (disabled by default)')
    parser.add_argument('--php-path', '-p', default='php', help='Path to PHP executable')
    parser.add_argument('--threads', '-t', type=int, default=4, help='Maximum number of threads to use')
    parser.add_argument('--quiet', '-q', action='store_true', help='Suppress verbose output')
    
    args = parser.parse_args()
    
    extractor = LocalTailwindExtractor(
        args.project_dir,
        args.output,
        args.execute_php,  # PHP çalıştırma artık varsayılan olarak kapalı
        args.php_path,
        args.threads,
        not args.quiet
    )
    
    extractor.extract()