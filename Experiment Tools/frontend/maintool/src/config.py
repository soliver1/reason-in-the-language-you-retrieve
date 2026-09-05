import os
import pathlib as pl
from dataclasses import dataclass

import datetime


@dataclass
class Settings:
    debug=True
    auth_use_secure_cookie=False

    database_path = pl.Path('frontend/database/database.db')

    use_tailwind = True
    tailwind_script_path = pl.Path('./scripts/tailwindcss/bin/tailwindcss')
    tailwind_src_file = 'frontend/shared/css/style.css'
    tailwind_target_file = 'frontend/shared/css/style_out.css'

    load_tool_directories = [
        'meisterwissen',
    ]

    use_update_con = True
    update_con_address = 'localhost'
    update_con_port = int(os.environ.get("BACKEND_PORT", 8002))

    route_prefix = ''


    fighter_mapping = {
        "1": "",
        "2": "",
        "3": "",
        "4": ""
    }
    ui_date = datetime.date(1924, 5, 15)
    ui_background = '/ui/background'
    fighter_default_image = ''



settings = Settings()
