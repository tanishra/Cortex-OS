from tools.web.search import search
from tools.web.weather import get_weather
from tools.email.gmail import send_email
from tools.os.system import open_file, list_directory, create_folder, delete_path, run_command
from tools.web.scraping import scrape_page
from tools.os.files import read_file, write_file, move_file, copy_file, delete_file
from tools.os.browser import search_google, search_youtube, open_github, open_stackoverflow, open_url
from tools.os.apps import open_app, quit_app, focus_app, list_apps
from tools.browser.control import open_new_tab, go_back, go_forward, search_on_page, click_element, switch_tab, scroll_page, close_all_tabs, close_current_tab, close_tab_by_index, close_tab_by_title


__all__ = ["search", "get_weather", "send_email","open_file","list_directory","create_folder","delete_path","run_command","scrape_page","read_file","write_file","move_file","copy_file","delete_file","open_url","search_google","search_youtube","open_github","open_stackoverflow","open_app","quit_app","focus_app","list_apps","open_new_tab","go_back","go_forward","search_on_page","click_element","switch_tab","scroll_page","close_all_tabs","close_current_tab","close_tab_by_index","close_tab_by_title"]