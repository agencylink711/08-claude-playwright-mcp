import os
import tempfile
import asyncio
import logging
from typing import Literal
from datetime import datetime
import psutil
import nest_asyncio
from playwright.async_api import async_playwright, Page
from mcp.server.fastmcp import FastMCP

nest_asyncio.apply()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class PlaywrightManager:
    """
    A singleton class to manage a single Playwright instance
    to be shared across all MCP tool calls.
    """
    
    _instance = None
    
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super(PlaywrightManager, cls).__new__(cls)
            cls._instance.initialized = False
        return cls._instance
    
    def __init__(
        self,
        browser_type: Literal['chromium', 'firefox', 'webkit'] = 'chromium',
        headless: bool = False,
        viewer_port: tuple = (1200, 900)
    ):
        if not self.initialized:
            self.browser_type = browser_type
            self.headless = headless
            self.viewport_width, self.viewport_height = viewer_port
            
            # These will be lazily initialized when needed
            self.playwright = None
            self.browser = None
            self.context = None
            self.page = None
            self.initialized = True
    
    async def ensure_browser(self) -> Page:
        """
        Ensure browser is initialized and return the page.
        
        Returns:
            Active Playwright page
        """
        if not self.playwright:
            logger.info('Starting Playwright')
            self.playwright = await async_playwright().start()
            
        if not self.browser:
            logger.info(f'Launching {self.browser_type} browser')
            browser_factory = getattr(self.playwright, self.browser_type)
            self.browser = await browser_factory.launch(headless=self.headless)

            self.context = await self.browser.new_context(
                viewport={'width': self.viewport_width, 'height': self.viewport_height } 
            )
            logger.info('Browser context created with custom viewport')
            
            self.page = await self.context.new_page()

        if not self.context:
            logger.info('Creating new browser context')
            self.context = await self.browser.new_context()
            
        if not self.page:
            logger.info('Creating new page')
            self.page = await self.context.new_page()
            
        return self.page
    
    async def close(self) -> None:
        """Close all browser resources explicitly."""
        logger.info('Closing browser resources')
        
        if self.page:
            await self.page.close()
            self.page = None
            
        if self.context:
            await self.context.close()
            self.context = None
            
        if self.browser:
            await self.browser.close()
            self.browser = None
            
        if self.playwright:
            await self.playwright.stop()
            self.playwright = None

mcp = FastMCP(
    name='PlaywrightTools',
    dependencies = ['playwright', 'nest_asyncio', 'psutil']
)

pw_manager = PlaywrightManager(browser_type='chromium', headless=False, viewer_port=(1200, 900))

work_dir = os.path.dirname(__file__)


@mcp.tool(
    name='Browser-Navigate',
    description='Navigate to a URL in the browser.'
)
async def browser_navigate(url: str) -> str:
    """
    Navigate to a URL in the browser.
    
    Args:
        url: The URL to navigate to
    
    Returns:
        Confirmation message
    """
    if not url or not isinstance(url, str):
        return 'Error: URL must be a non-empty string'
    
    # Ensure pw_manager instance exists
    global pw_manager
    if pw_manager is None:
        pw_manager = PlaywrightManager(browser_type='chromium', headless=False)
    
    page = await pw_manager.ensure_browser()
    logger.info(f'Navigating to {url}')
    
    try:
        await page.goto(url, wait_until='domcontentloaded')
        await page.wait_for_load_state('load', timeout=5000)
    except Exception as e:
        logger.warning(f'Page load timeout or error: {str(e)}')
        return f'Error navigating to {url}: {str(e)}'
    
    return f"Navigated to {url}"

@mcp.tool(
    name='Browser-Close',
    description='Close all browser resources explicitly.'
)
async def browser_close() -> str:
    """
    Close all browser resources explicitly.
    
    Returns:
        Closure confirmation
    """
    await pw_manager.close()
    return 'Browser closed'


@mcp.tool(
    name='Kill-All-Chrome-Instances',
    description='Kill all Chrome instances generated via Playwright.'
)
async def kill_all_chrome_instances() -> str:
    """
    Kill all Chrome instances generated via Playwright.

    Returns:
        A confirmation message or an error message.
    """
    logger.info('Attempting to kill all Chrome instances generated via Playwright.')

    try:
        # Iterate through all running processes
        for process in psutil.process_iter(attrs=['pid', 'name', 'exe']):
            try:
                # Check if the process name matches Chrome and its executable path contains "playwright"
                if (
                    process.info['name'] 
                    and 'chrome' in process.info['name'].lower() 
                    and process.info['exe'] 
                    and 'playwright' in process.info['exe'].lower()
                ):
                    logger.info(
                        f'Terminating process: {process.info["name"]} '
                        f'(PID: {process.info["pid"]}, Path: {process.info["exe"]})'
                    )
                    process.terminate()  # Terminate the process
            except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
                logger.warning(f'Could not terminate process: {str(e)}')

        return 'All Chrome instances generated via Playwright have been terminated.'
    except Exception as e:
        error_msg = f'Failed to kill Chrome instances: {str(e)}'
        logger.error(error_msg)
        return error_msg
    

@mcp.tool(
    name='Browser-Fill',
    description='Fill a form field with text.'
)
async def browser_fill(selector: str, text: str) -> str:
    """
    Fill a form field with text.
    
    Args:
        selector: CSS or XPath selector to find the form field
        text: Text to fill the form field with
    
    Returns:
        Fill confirmation
    """
    if not selector or not isinstance(selector, str):
        return 'Error: Selector must be a non-empty string'
    if not isinstance(text, str):
        return 'Error: Text must be a string'
    
    page = await pw_manager.ensure_browser()
    logger.info(f'Filling text in selector: {selector}')
    
    try:
        await page.fill(selector, text)
    except Exception as e:
        error_msg = f'Could not fill element: {str(e)}'
        logger.error(error_msg)
        return error_msg
    
    return f"Filled text in element with selector '{selector}'"


@mcp.tool(
    name='Browser-Find-By-XPath',
    description='Find elements using an XPath expression and return their count.'
)
async def browser_find_by_xpath(xpath: str) -> str:
    """
    Find elements using an XPath expression and return their count.
    
    Args:
        xpath: XPath expression to find elements
    
    Returns:
        Count of matching elements
    """
    if not xpath or not isinstance(xpath, str):
        return 'Error: XPath must be a non-empty string'
    
    # Ensure xpath is formatted properly
    if not xpath.startswith('//') and not xpath.startswith('xpath='):
        xpath = f'xpath={xpath}'
    
    page = await pw_manager.ensure_browser()
    logger.info(f'Finding elements with XPath: {xpath}')
    
    try:
        count = len(await page.query_selector_all(xpath))
        return f"Found {count} elements matching XPath '{xpath}'"
    except Exception as e:
        error_msg = f'Error finding elements: {str(e)}'
        logger.error(error_msg)
        return error_msg


@mcp.tool(
    name='Browser-Go-Back',
    description='Go back to the previous page in the browser.'
)
async def browser_go_back() -> str:
    """
    Go back to the previous page in the browser.
    
    Returns:
        Navigation result
    """
    page = await pw_manager.ensure_browser()
    logger.info('Navigating back')
    
    await page.go_back()
    
    return 'Navigated back'

@mcp.tool(
    name='Browser-Reload',
    description='Reload the current page.'
)
async def browser_reload() -> str:
    """
    Reload the current page.
    
    Returns:
        Reload confirmation
    """
    page = await pw_manager.ensure_browser()
    logger.info('Reloading page')
    
    await page.reload()
    
    return 'Page reloaded'


@mcp.tool(
    name='Browser-Click',
    description='Click on an element matching the selector',
)
async def browser_click(selector: str) -> str:
    """
    Click on an element matching the selector.
    
    Args:
        selector: CSS or XPath selector to find the element
    
    Returns:
        Click confirmation
    """
    if not selector or not isinstance(selector, str):
        return 'Error: Selector must be a non-empty string'
    
    page = await pw_manager.ensure_browser()
    logger.info(f'Clicking element with selector: {selector}')
    
    try:
        await page.click(selector, timeout=5000)
    except Exception as e:
        error_msg = f'Could not click element: {str(e)}'
        logger.error(error_msg)
        return error_msg
    
    return f"Clicked element with selector '{selector}'"


@mcp.tool(
    name='Browser-Save-As-PDF',
    description='Save the current page as a PDF.'
)
async def browser_save_as_pdf(landscape: bool = False, format: str = None) -> str:
    """
    Save the current page as a PDF.
    
    Args:
        landscape: Whether to save in landscape orientation
        format: Paper format (e.g., 'A4', 'letter') or null for default
    
    Returns:
        Path to saved PDF file
    """
    if pw_manager.browser_type != 'chromium' or not pw_manager.headless:
        await pw_manager.close()
        
        pw_manager.browser_type = 'chromium'
        pw_manager.headless = False
    
    page = await pw_manager.ensure_browser()
    logger.info('Generating PDF')
    
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    file_name = os.path.join(
        tempfile.gettempdir(), 
        f'page_{timestamp}.pdf'
    )
    
    pdf_options = {}
    if landscape:
        pdf_options['landscape'] = True
    if format:
        pdf_options['format'] = format
    
    try:
        await page.pdf(path=file_name, **pdf_options)
    except Exception as e:
        error_msg = f'Failed to generate PDF: {str(e)}'
        logger.error(error_msg)
        return error_msg
    
    return f'PDF saved to {file_name}'


@mcp.tool(
    name='Browser-Screenshot',
    description='Take a screenshot of the current page or a specific element.'
)
async def browser_screenshot(selector: str = None, file_path: str = None) -> str:
    """
    Take a screenshot of the current page or a specific element.
    
    Args:
        selector: Optional CSS or XPath selector to capture a specific element
    
    Returns:
        Path to saved screenshot
    """
    page = await pw_manager.ensure_browser()
    logger.info('Taking screenshot')
    
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    file_name = os.path.join(
        tempfile.gettempdir(), 
        f'screenshot_{timestamp}.png'
    )
    
    try:
        if (selector):
            logger.info(f'Taking screenshot of element: {selector}')
            element = await page.query_selector(selector)
            if not element:
                return f"Error: Could not find element with selector '{selector}'"
            await element.screenshot(path=file_name)
        else:
            await page.screenshot(path=file_name)
    except Exception as e:
        error_msg = f'Failed to take screenshot: {str(e)}'
        logger.error(error_msg)
        return error_msg
    
    return f'Screenshot saved to {file_name}'


@mcp.tool(
    name='Browser-Scroll-To-Top',
    description='Scroll the page to the very top.'
)
async def browser_scroll_to_top() -> str:
    """
    Scroll the page to the very top.
    
    Returns:
        Scroll confirmation
    """
    page = await pw_manager.ensure_browser()
    logger.info('Scrolling to top of page')
    
    try:
        # Use smooth scrolling for better user experience
        await page.evaluate("""() => {
            window.scrollTo({
                top: 0,
                left: 0,
                behavior: 'smooth'
            });
        }""")
        
        # Small wait to allow smooth scrolling to complete
        await asyncio.sleep(0.5)
        return 'Scrolled to top of page'
    except Exception as e:
        error_msg = f'Failed to scroll to top: {str(e)}'
        logger.error(error_msg)
        return error_msg


@mcp.tool(
    name='Browser-Scroll-To-Bottom',
    description='Scroll the page to the very bottom.'
)
async def browser_scroll_to_bottom() -> str:
    """
    Scroll the page to the very bottom.
    
    Returns:
        Scroll confirmation
    """
    page = await pw_manager.ensure_browser()
    logger.info("Scrolling to bottom of page")
    
    try:
        # Calculate document height and scroll to it
        await page.evaluate("""() => {
            const scrollHeight = Math.max(
                document.body.scrollHeight,
                document.documentElement.scrollHeight,
                document.body.offsetHeight,
                document.documentElement.offsetHeight,
                document.body.clientHeight,
                document.documentElement.clientHeight
            );
            
            window.scrollTo({
                top: scrollHeight,
                left: 0,
                behavior: 'smooth'
            });
        }""")
        
        # Small wait to allow smooth scrolling to complete
        await asyncio.sleep(0.5)
        return "Scrolled to bottom of page"
    except Exception as e:
        error_msg = f"Failed to scroll to bottom: {str(e)}"
        logger.error(error_msg)
        raise ValueError(error_msg)


@mcp.tool(
    name='Browser-Scroll-To-Element',
    description='Scroll the page until the specified element is in view.'
)
async def browser_scroll_to_element(selector: str) -> str:
    """
    Scroll the page until the specified element is in view.
    
    Args:
        selector: CSS or XPath selector for the element to scroll to
    
    Returns:
        Scroll confirmation
    """
    if not selector or not isinstance(selector, str):
        return 'Error: Selector must be a non-empty string'
    
    page = await pw_manager.ensure_browser()
    logger.info(f'Scrolling to element with selector: {selector}')
    
    try:
        # First check if the element exists
        element = await page.query_selector(selector)
        if not element:
            return f'Error: No element found with selector: {selector}'
        
        # Scroll element into view with smooth behavior
        await page.evaluate(f"""
            (selector) => {{
                const element = document.querySelector(selector);
                if (element) {{
                    element.scrollIntoView({{
                        behavior: 'smooth',
                        block: 'center'
                    }});
                }}
            }}
        """, selector)
        
        # Small wait to allow smooth scrolling to complete
        await asyncio.sleep(0.5)
        return f"Scrolled to element with selector '{selector}'"
    except Exception as e:
        error_msg = f'Failed to scroll to element: {str(e)}'
        logger.error(error_msg)
        return error_msg


@mcp.tool(
    name='Get-Current-URL',
    description='Get the URL of the current page.'
)
async def get_current_url() -> str:
    """
    Get the URL of the current page.
    
    Returns:
        Current URL
    """
    page = await pw_manager.ensure_browser()
    url = page.url
    
    return url


@mcp.tool(
    name='Get-Element-HTML',
    description='Get the HTML content of a specific element using XPath.'
)
async def get_element_html(xpath: str) -> str:
    """
    Get the HTML content of a specific element using XPath.

    Args:
        xpath: XPath query to find the element

    Returns:
        HTML content of the element or error message
    """
    if not xpath or not isinstance(xpath, str):
        return 'Error: XPath must be a non-empty string'

    page = await pw_manager.ensure_browser()
    logger.info(f'Getting HTML content from element with XPath: {xpath}')

    try:
        element = await page.query_selector(f'xpath={xpath}')
        if not element:
            return f'Error: No element found with XPath: {xpath}'

        html_content = await element.inner_html()
        return html_content
    except Exception as e:
        error_msg = f'Error getting element HTML: {str(e)}'
        logger.error(error_msg)
        return error_msg
    

@mcp.tool(
    name='Get-Element-Text',
    description='Get the text content of an element using XPath.'
)
async def get_element_text(xpath: str) -> str:
    """
    Get the text content of an element using XPath.
    
    Args:
        xpath: XPath query to find the element
    
    Returns:
        Text content of the element or error message
    """
    if not xpath or not isinstance(xpath, str):
        return 'Error: XPath must be a non-empty string'
    
    page = await pw_manager.ensure_browser()
    logger.info(f'Getting text from element with XPath: {xpath}')
    
    try:
        element = await page.query_selector(f'xpath={xpath}')
        if not element:
            return f'Error: No element found with XPath: {xpath}'
        
        text = await element.inner_text()
        return text
    except Exception as e:
        error_msg = f'Error getting element text: {str(e)}'
        logger.error(error_msg)
        return error_msg


@mcp.tool(
    name='Get-Page-Content',
    description='Get the text content of the current page.'
)
async def get_page_content() -> str:
    """
    Get the text content of the current page.
    
    Returns:
        Text content of the page
    """
    page = await pw_manager.ensure_browser()
    text_content = await page.evaluate("""() => {
        return document.body.innerText;
    }""")
    
    return text_content


@mcp.tool(
    name='Get-Page-HTML',
    description='Get the HTML content of the current page.'
)
async def get_page_html() -> str:
    """
    Get the HTML content of the current page.
    
    Returns:
        HTML content of the page
    """
    page = await pw_manager.ensure_browser()
    html_content = await page.content()
    
    return html_content


@mcp.tool(
    name='Get-Page-Title',
    description='Get the title of the current page.'
)
async def get_page_title() -> str:
    """
    Get the title of the current page.
    
    Returns:
        Page title
    """
    page = await pw_manager.ensure_browser()
    title = await page.title()
    
    return title


@mcp.tool(
    name='Save-Element-As-HTML',
    description='Save a specific element\'s HTML content to a file using XPath.'
)
async def save_element_as_html(xpath: str, file_path: str = None) -> str:
    """
    Save a specific element's HTML content to a file using XPath.

    Args:
        xpath: XPath query to find the element
        file_path: Optional path to save the HTML file. If not provided, a default path will be used.

    Returns:
        Path to the saved HTML file
    """
    if not xpath or not isinstance(xpath, str):
        return 'Error: XPath must be a non-empty string'

    page = await pw_manager.ensure_browser()
    logger.info(f'Saving HTML content of element with XPath: {xpath}')

    if not file_path:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        file_path = os.path.join(work_dir, f'element_{timestamp}.html')

    try:
        element = await page.query_selector(f'xpath={xpath}')
        if not element:
            return f'Error: No element found with XPath: {xpath}'

        html_content = await element.evaluate('(node) => node.outerHTML')
        if not html_content:
            return f'Error: Could not extract HTML from element with XPath: {xpath}'

        full_html = f"""<!DOCTYPE html>
        <html>
        <head>
            <meta charset='utf-8'>
            <title>Extracted Element HTML</title>
        </head>
        <body>
            <!-- Element with XPath: {xpath} -->
            {html_content}
        </body>
        </html>"""

        # Save to file
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(full_html)

        return f'Element HTML saved to {file_path}'
    except Exception as e:
        error_msg = f'Failed to save element HTML: {str(e)}'
        logger.error(error_msg)
        return error_msg


@mcp.tool(
    name='Save-Page-As-HTML',
    description='Save the current page\'s HTML content to a file.'
)
async def save_page_as_html(file_path: str = None) -> str:
    """
    Save the current page's HTML content to a file.
    
    Args:
        file_path: Optional path to save the HTML file. If not provided, a default path will be used.
    
    Returns:
        Path to the saved HTML file
    """
    page = await pw_manager.ensure_browser()
    logger.info('Saving current page as HTML')
    
    if not file_path:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        file_path = os.path.join(work_dir, f'page_{timestamp}.html')
    
    try:
        html_content = await page.content()
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(html_content)
    except Exception as e:
        error_msg = f'Failed to save HTML: {str(e)}'
        logger.error(error_msg)
        return error_msg
    
    return f'HTML saved to {file_path}'


@mcp.tool(
    name='Save-Page-Screenshot',
    description='Save a screenshot of the current page.'
)
async def save_page_screenshot(file_path: str = None) -> str:
    """
    Save a screenshot of the current page.
    
    Args:
        file_path: Optional path to save the screenshot. If not provided, a default path will be used.
    
    Returns:
        Path to the saved screenshot
    """
    page = await pw_manager.ensure_browser()
    logger.info('Taking screenshot of the current page')
    
    if not file_path:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        file_path = os.path.join(work_dir, f'screenshot_{timestamp}.png')
    else:
        file_path = os.path.join(file_path)

    try:
        await page.screenshot(path=file_path)
    except Exception as e:
        error_msg = f'Failed to take screenshot: {str(e)}'
        logger.error(error_msg)
        return error_msg
    
    return f'Screenshot saved to {file_path}'


@mcp.tool(
    name='Clear-Field',
    description='Clear the content of a specific input field using XPath.'
)
async def clear_field(xpath: str) -> str:
    """
    Clear the content of a specific input field using XPath.

    Args:
        xpath: XPath query to find the input field

    Returns:
        Confirmation message or error message
    """
    if not xpath or not isinstance(xpath, str):
        return 'Error: XPath must be a non-empty string'

    page = await pw_manager.ensure_browser()
    logger.info(f'Clearing content of input field with XPath: {xpath}')

    try:
        element = await page.query_selector(f'xpath={xpath}')
        if not element:
            return f'Error: No input field found with XPath: {xpath}'

        await element.fill('')  # Clear the field by filling it with an empty string
        return f'Cleared content of input field with XPath: {xpath}'
    except Exception as e:
        error_msg = f'Failed to clear input field: {str(e)}'
        logger.error(error_msg)
        return error_msg


@mcp.tool(
    name='Browser-Press-Key',
    description='Press a key on the keyboard.'
)
async def browser_press_key(key: str) -> str:
    """
    Press a key on the keyboard.
    
    Args:
        key: Key to press (e.g., 'Enter', 'Tab', 'ArrowDown')
    
    Returns:
        Key press confirmation
    """
    if not key or not isinstance(key, str):
        return 'Error: Key must be a non-empty string'
    
    page = await pw_manager.ensure_browser()
    logger.info(f'Pressing key: {key}')
    
    try:
        await page.keyboard.press(key)
    except Exception as e:
        error_msg = f'Error pressing key: {str(e)}'
        logger.error(error_msg)
        return error_msg
    
    return f"Pressed key {key}"


@mcp.tool(
    name='Browser-Scroll-One-Step',
    description='Scroll the page by one step.'
)
async def browser_scroll_one_step(step: int = 100) -> str:
    """
    Scroll the page by one step.

    Args:
        step: The number of pixels to scroll. Positive for down, negative for up.

    Returns:
        Scroll confirmation message.
    """
    if not isinstance(step, int):
        return 'Error: Step must be an integer'

    page = await pw_manager.ensure_browser()
    logger.info(f'Scrolling the page by {step} pixels')

    try:
        await page.evaluate(f'window.scrollBy(0, {step})')
        return f'Scrolled the page by {step} pixels'
    except Exception as e:
        error_msg = f'Failed to scroll the page: {str(e)}'
        logger.error(error_msg)
        return error_msg



@mcp.tool(
    name='Clear-Browser-Data',
    description='Clear cookies, localStorage, and sessionStorage.'
)
async def clear_browser_data() -> str:
    """
    Clear cookies, localStorage, and sessionStorage.
    
    Returns:
        Confirmation message
    """
    page = await pw_manager.ensure_browser()
    logger.info('Clearing browser data')
    
    await page.context.clear_cookies()
    await page.evaluate('() => { localStorage.clear(); sessionStorage.clear(); }')
    
    return 'Browser data cleared'

@mcp.tool(
    name='Get-Cookies',
    description='Get all cookies for the current page.'
)
async def get_cookies() -> str:
    """
    Get all cookies for the current page.
    
    Returns:
        JSON string of cookies
    """
    page = await pw_manager.ensure_browser()
    logger.info('Getting cookies')
    
    cookies = await page.context.cookies()
    return json.dumps(cookies, indent=4)

if __name__ == "__main__":
    mcp.run(transport='stdio')