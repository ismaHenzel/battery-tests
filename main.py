# AI CODE GENERATED, I JUST USED TO MEASURE MY BATERY DISCHARGING USING POWERSTAT

import time
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

# A list of safe, varied sites to keep open in tabs
URLS = [
    "https://en.wikipedia.org/wiki/Special:Random",
    "https://news.ycombinator.com",
    "https://github.com/trending",
    "https://stackoverflow.com",
    "https://www.bbc.com/news",
    "https://www.youtube.com",
    "https://www.youtube.com/watch?v=W5FI97ovWog",
    "https://medium.com/"
]

def run_realistic_battery_test(cycles=50):
    print("Starting realistic multi-tab battery drain test...")
    
    # Initialize Chrome
    options = webdriver.ChromeOptions()
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    
    try:
        # 1. Open all URLs in separate tabs
        print("Opening initial tabs...")
        for index, url in enumerate(URLS):
            if index == 0:
                # First URL loads in the default open window
                driver.get(url)
            else:
                # Open a new tab and switch to it for subsequent URLs
                driver.switch_to.new_window('tab')
                driver.get(url)
            time.sleep(2) # Give each tab a moment to start loading
            
        # 2. Cycle through the open tabs
        # driver.window_handles contains a list of IDs for all open tabs
        tabs = driver.window_handles 
        
        for i in range(cycles):
            print(f"\n--- Cycle {i+1} of {cycles} ---")
            
            for tab_index, tab_handle in enumerate(tabs):
                # Switch to the specific tab
                driver.switch_to.window(tab_handle)
                
                print(f"Tab {tab_index + 1}: Refreshing and scrolling...")
                driver.refresh()
                
                # Allow the page to load after refreshing
                time.sleep(3)
                
                # Get the new total height of the page
                scroll_height = driver.execute_script("return document.body.scrollHeight")
                
                # Scroll down in increments
                for step in range(0, scroll_height, 400):
                    driver.execute_script(f"window.scrollTo(0, {step});")
                    time.sleep(0.5)
                
                # Pause at the bottom of the page before switching tabs
                time.sleep(2)
                
    except KeyboardInterrupt:
        print("\nTest interrupted by user.")
    except Exception as e:
        print(f"\nAn error occurred: {e}")
    finally:
        print("\nClosing browser and cleaning up...")
        driver.quit()

if __name__ == "__main__":
    run_realistic_battery_test(cycles=100)
