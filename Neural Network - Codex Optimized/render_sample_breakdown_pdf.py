from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path('/Users/chadoconnor/Neural Network')
HTML = ROOT / 'sample_player_breakdown_source.html'
PDF = ROOT / 'sample_player_breakdown.pdf'


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(HTML.resolve().as_uri(), wait_until='networkidle')
        page.pdf(
            path=str(PDF),
            format='Letter',
            print_background=True,
            prefer_css_page_size=True,
            margin={
                'top': '0in',
                'right': '0in',
                'bottom': '0in',
                'left': '0in',
            },
        )
        browser.close()
    print(PDF)


if __name__ == '__main__':
    main()
