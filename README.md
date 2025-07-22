# Warcraft Logs to Mythic Dungeon Tool (MDT) Converter

This Python script automatically converts the trash pulls from a Warcraft Logs report into an importable string for the Mythic Dungeon Tool (MDT) addon in World of Warcraft.

This allows you to easily replicate, analyze, and share dungeon routes that you or others have completed.

## Features
Fetches complete event data for a specific dungeon run from a WCL report using the official v2 API.

Intelligently groups enemy mobs into distinct pulls based on combat timing.

Generates a Mythic Dungeon Tool (MDT) import string that replicates the pulls from the log.

Outputs the string to both the console and a .txt file for easy access.

Supports specifying a particular fight ID or defaulting to the last Mythic+ run in the report.

## Prerequisites
Before you begin, ensure you have the following installed:

- Python 3.6+: You can download it from python.org.

- pip: Python's package installer, which usually comes with modern Python installations.

## Setup & Installation

### 1. Get Warcraft Logs API Credentials
To use this script, you need a Client ID and Client Secret from Warcraft Logs.

Log in to your Warcraft Logs account.

Navigate to your profile settings by clicking your avatar and selecting Settings.

In the left-hand menu, go to the API Clients section.

Click Create Client and fill out the form:

Name: MDT Converter Script (or any name you prefer)

Redirect URL: http://localhost

Description: A brief description of the script.

After creating the client, you will be provided with a Client ID and a Client Secret. Keep these safe and ready to use.

### 2. Set Up the Project
It is highly recommended to use a Python virtual environment to manage dependencies.

#### 1. Clone or download the repository and navigate into the project directory

```
cd /path/to/your/project
```

#### 2. Create a virtual environment

```
python -m venv venv
```

#### 3. Activate the virtual environment
On Windows:

```
venv\Scripts\activate
```

On macOS/Linux:

```
source venv/bin/activate
```

#### 4. Install the required libraries

```
pip install requests
```

##Usage
The script is run from the command line with arguments providing your API credentials and the report URL.

### 3. Command Syntax

```
python wcl_to_mdt.py --client-id "YOUR_CLIENT_ID" --client-secret "YOUR_CLIENT_SECRET" --url "WCL_REPORT_URL" [--fight FIGHT_ID]
```

Arguments

```
--client-id: (Required) Your Warcraft Logs API v2 Client ID.

--client-secret: (Required) Your Warcraft Logs API v2 Client Secret.

--url: (Required) The full URL of the Warcraft Logs report you want to analyze.

--fight: (Optional) The specific fight ID from the report to convert. If omitted, the script will automatically use the last Mythic+ run in the report.
```

Example

```
python wcl_to_mdt.py \
  --client-id "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx" \
  --client-secret "yourSecretHerexxxxxxxxxxxxxxxxxxxx" \
  --url "https://www.warcraftlogs.com/reports/akzvc9Hq2b4BpZYK" \
  --fight 1
```

### 4. Output
After running successfully, the script will:

Print the generated MDT import string directly to your console.

Save the same string to a text file named mdt_import_<reportID>_fight_<fightID>.txt in the project directory.

You can then copy this string and import it directly into the Mythic Dungeon Tool addon in-game.

