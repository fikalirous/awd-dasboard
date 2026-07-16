# AWD Farmer Progress Dashboard
## Complete Beginner Setup Guide

---

## WHAT YOU WILL END UP WITH

A live web dashboard at a public URL like:
`https://your-awd-dashboard.streamlit.app`

Your NGO client can open this link in any browser. It automatically shows
the latest data from your Google Sheets every hour.

---

## OVERVIEW OF STEPS

```
Step 1  →  Install Python on your computer
Step 2  →  Download the dashboard files
Step 3  →  Connect your Google Sheets
Step 4  →  Test it on your computer
Step 5  →  Put the files on GitHub (free)
Step 6  →  Deploy on Streamlit Cloud (free)
Step 7  →  Share the live URL with your client
```

---

## STEP 1 — INSTALL PYTHON

Python is the programming language this dashboard is written in.
You need to install it once on your computer.

### On Windows:
1. Go to https://www.python.org/downloads/
2. Click the big yellow button "Download Python 3.12.x"
3. Run the downloaded file (.exe)
4. IMPORTANT: On the first screen, tick the checkbox that says
   "Add Python to PATH" before clicking Install
5. Click "Install Now"
6. When it finishes, click Close

### On Mac:
1. Go to https://www.python.org/downloads/
2. Click the big yellow button "Download Python 3.12.x"
3. Run the downloaded file (.pkg)
4. Follow the installer steps (Next, Next, Install)

### Check it worked:
- Windows: press Windows key, type "cmd", press Enter
- Mac: press Cmd+Space, type "terminal", press Enter

In the black window that opens, type:
```
python --version
```
Press Enter. You should see something like:  Python 3.12.3
If you see a version number, Python is installed correctly.

---

## STEP 2 — DOWNLOAD THE DASHBOARD FILES

You need these files:
- app.py
- requirements.txt
- README.md (this file)
- .streamlit/config.toml (locks the dashboard to one consistent light colour theme —
  keep it inside a folder named ".streamlit" next to app.py)

Create a folder on your computer. Name it something like:
  awd-dashboard

Put all three files inside that folder.

---

## STEP 3 — CONNECT YOUR GOOGLE SHEETS

### 3a. Publish your Google Sheets as CSV

You need to do this TWICE — once for Master Analysis, once for Summary.

For EACH sheet:
1. Open your Google Sheet in a browser
2. Click "File" in the top menu
3. Hover over "Share"
4. Click "Publish to web"
5. A popup window appears
6. In the FIRST dropdown (it probably says "Entire Document"),
   click it and select the sheet tab name:
   - First time: select "Master Analysis"
   - Second time: select "Summary"
7. In the SECOND dropdown (it probably says "Web page"),
   click it and select "Comma-separated values (.csv)"
8. Click the green "Publish" button
9. A message appears asking "Are you sure?" — click OK
10. A URL appears in a box — COPY IT (Ctrl+C on Windows, Cmd+C on Mac)
11. Paste it somewhere safe (like Notepad or a text document)
12. Close the popup
13. Repeat steps 2-12 for the second sheet tab

The URLs will look something like this:
https://docs.google.com/spreadsheets/d/e/2PACX-1vRZgkq.../pub?gid=0&single=true&output=csv

### 3b. Paste the URLs into app.py

1. Open the "awd-dashboard" folder
2. Right-click on "app.py"
3. Open with → Notepad (Windows) or TextEdit (Mac)
4. Near the top of the file, find these two lines:

   MASTER_ANALYSIS_URL = (
       "PASTE_YOUR_MASTER_ANALYSIS_CSV_URL_HERE"
   )

   SUMMARY_URL = (
       "PASTE_YOUR_SUMMARY_CSV_URL_HERE"
   )

5. Replace the placeholder text with your actual URLs:

   MASTER_ANALYSIS_URL = (
       "https://docs.google.com/spreadsheets/d/e/YOUR_ACTUAL_URL_HERE/pub?gid=0&single=true&output=csv"
   )

   SUMMARY_URL = (
       "https://docs.google.com/spreadsheets/d/e/YOUR_ACTUAL_URL_HERE/pub?gid=123456&single=true&output=csv"
   )

6. Save the file (Ctrl+S on Windows, Cmd+S on Mac)

---

## STEP 4 — TEST ON YOUR COMPUTER

### 4a. Open your terminal / command prompt

Windows:
- Press the Windows key
- Type "cmd"
- Press Enter
- A black window opens

Mac:
- Press Cmd + Space
- Type "terminal"
- Press Enter
- A white or black window opens

### 4b. Navigate to your project folder

In the terminal, you need to go to the "awd-dashboard" folder.

Windows example (if your folder is on the Desktop):
```
cd Desktop\awd-dashboard
```

Mac example (if your folder is on the Desktop):
```
cd Desktop/awd-dashboard
```

After pressing Enter, the prompt should show your folder name.

### 4c. Install the required libraries (do this once)

Copy and paste this command, then press Enter:
```
pip install -r requirements.txt
```

This downloads the libraries the dashboard needs.
It may take 1-2 minutes. You will see a lot of text scrolling — this is normal.
When it finishes, you will see your cursor again.

### 4d. Run the dashboard

Copy and paste this command, then press Enter:
```
streamlit run app.py
```

You will see something like:
  You can now view your Streamlit app in your browser.
  Local URL: http://localhost:8501

Your browser will open automatically showing the dashboard.
If it does not open, type http://localhost:8501 into your browser manually.

To stop the dashboard: go back to the terminal and press Ctrl+C

---

## STEP 5 — PUT YOUR FILES ON GITHUB

GitHub is a free website that stores code. Streamlit Cloud reads your code
from GitHub to deploy your dashboard.

### 5a. Create a GitHub account

1. Go to https://github.com
2. Click "Sign up"
3. Enter your email, create a password, choose a username
4. Verify your email address
5. You now have a GitHub account

### 5b. Create a new repository (a folder on GitHub)

1. Log in to https://github.com
2. Click the "+" icon in the top right corner
3. Click "New repository"
4. Repository name: type "awd-dashboard"
5. Make sure "Public" is selected (Streamlit Cloud needs to see it)
6. Tick the checkbox "Add a README file"
7. Click the green "Create repository" button
8. Your repository page opens

### 5c. Upload your files

1. On your repository page, click "Add file"
2. Click "Upload files"
3. Drag and drop your files onto the page:
   - app.py
   - requirements.txt
   - README.md
   - the whole ".streamlit" folder (containing config.toml) — GitHub's upload
     page accepts dragging a folder directly; if it only accepts single files,
     create the folder ".streamlit" in the repo first ("Add file" → "Create new
     file", type ".streamlit/config.toml" as the filename) and paste its contents
4. Scroll down
5. Click the green "Commit changes" button
6. All files are now on GitHub

---

## STEP 6 — DEPLOY ON STREAMLIT CLOUD

This makes your dashboard available at a public URL.

1. Go to https://share.streamlit.io
2. Click "Sign in with GitHub"
3. Log in with your GitHub account
4. Click "New app"
5. In "Repository", type: your-github-username/awd-dashboard
   (replace "your-github-username" with your actual GitHub username)
6. In "Branch", leave it as "main"
7. In "Main file path", type: app.py
8. Click "Deploy!"
9. A loading screen appears — wait 2-3 minutes
10. Your dashboard is now live!

The URL will be something like:
https://your-github-username-awd-dashboard-app-xxxxxx.streamlit.app

Copy this URL and share it with your NGO client.

---

## STEP 7 — UPDATING YOUR DASHBOARD

### If your Google Sheets data changes:
Nothing to do! The dashboard re-downloads data every hour automatically.
Your client can also click "Refresh Data" in the sidebar to get data immediately.

### If you want to change the app code:
1. Edit app.py on your computer
2. Go to your GitHub repository
3. Click on "app.py" in the file list
4. Click the pencil icon (Edit)
5. Paste your new code
6. Click "Commit changes"
7. Streamlit Cloud will automatically redeploy in about 1 minute

---

## DASHBOARD FEATURES

Note on terminology: the Google Sheet stores the field-type column as
"Experimental" / "Control". Every page in the dashboard displays the
"Experimental" group as **Treatment** instead — this is just a display label;
you don't need to change anything in your Google Sheet.

Every metric card, chart heading, and table column has a small "?" help icon —
hover over it for a plain-English definition of that variable, taken from
`AWD_Explainer_Document.docx`.

### Sidebar (left panel)
- Date range picker — filter to a specific time period
- Village multi-select — show one or more villages
- Field type selector — All / Treatment / Control
- Refresh button — force reload data from Google Sheets

### Tab 1 — Programme Overview
- KPI metric cards (farmers, drying events, safe zone %, BGL comparison,
  irrigations Reported vs Calculated)
- Weekly water level trend: Treatment vs Control
- Phase distribution donut chart — FL phases grouped together, then RL phases
- Village comparison bar charts (BGL + drying events)
- Drying duration by crop growth stage (0-30, 30-60, 60-90, 90+ DAS)

### Tab 2 — Treatment vs Control (Performance Comparison)
- Village dropdown to scope the comparison
- Programme-wide weekly water level trend for all Treatment vs all Control
  farmers in the selected villages
- Farmer-level drill-down: pick one Treatment farmer and one Control farmer
  and overlay their daily water-level trend directly
- Season metrics shown side by side for the two selected farmers (drying
  events, irrigations reported/calculated, water added, Gopal depth, etc.)
- A "Performance Index" radar chart scaling each metric 0–100 so the two
  farmers can be compared on one chart regardless of units

### Tab 3 — Farmer Summary
- Searchable, sortable table of all farmers with key season metrics,
  including both Irrigations Reported and Irrigations Calculated
- Filter by village and type
- Top 15 farmers by irrigation events — Reported vs Calculated (bar chart)
- Top 15 farmers by drying events (bar chart)
- CSV download button

### Tab 4 — Farmer Deep Dive
- Select village → type → individual farmer
- Season summary metrics pulled from Summary sheet, including Irrigations
  Reported and Irrigations Calculated side by side
- Full PP reading timeline with:
  - Safe zone green band
  - Irrigation markers — ▲ reported, ◇ calculated (water level rose >2cm)
  - Phase colour bars below the timeline (FL group, then RL group)
- BGL area chart (In ref to surface)
- Phase distribution donut
- Raw daily data table (expandable), including the derived
  "Irrigation Calculated" column

### Tab 5 — Water & Irrigation
- Programme-level totals: water added, recharged, TNAU baseline, savings %
- Total water added by village (Treatment vs Control)
- Gopal depth distribution histogram
- Irrigations Reported vs Calculated by village (bar chart)

### Tab 6 — Data Explorer
- Full Master Analysis flat table with search and filters
- Full Summary table with search
- CSV download for both

---

## COMMON PROBLEMS AND FIXES

**Problem:** "No data loaded" appears when I run the app
**Fix:** Check that your CSV URLs in app.py are correct. Make sure you published
        the sheets and copied the full URL including "https://"

**Problem:** "Error loading Master Analysis" appears
**Fix:** The Google Sheet may not be published. Go back to Step 3a and make
        sure you clicked "Publish" (not just Share).

**Problem:** The page is blank or shows an error after changing app.py
**Fix:** Check you saved app.py correctly. In the terminal, press Ctrl+C
        to stop, then run "streamlit run app.py" again.

**Problem:** pip install gives an error about permissions (Windows)
**Fix:** Run: pip install --user -r requirements.txt

**Problem:** Column names not found in the data
**Fix:** Open your Master Analysis or Summary sheet and check the exact header
        names match what is listed in the COLUMN NAMES section of app.py.
        Even one extra space or capital letter will cause a mismatch.

---

## COLUMN NAMES THIS DASHBOARD EXPECTS

### Master Analysis (21 columns)
A: Farmer Name
B: Village (Gram Panchayat)
C: Type
D: Method of Cultivation
E: Land Area (acres)
F: Date of Sowing
G: CRP Incharge
H: Date
I: Days Since Sowing
J: PP Reading (cm)
K: Duplicate? (count)
L: Zero Replaced?
M: In ref to surface
N: FL / RL
O: Phase
P: Change in WL (cm)
Q: Irrigated Water (cm)
R: Irrigated Water (m3)
S: Irrig. Depth Gopal (cm)
T: Irrigation Reported
U: Days Monitored

### Summary (key columns used)
Farmer Name, Village (Gram Panchayat), Type, Land Area (acres),
Days Monitored, No. of Drying Events, Days Water Above Surface,
Days Water Below Surface, Dry Days (>=25cm),
No. Irrigations (a) Reported, No. Irrigations (b) Calculated,
Total Water Added (mm), Total Water Added (m3),
Total Water Recharged (m3), Avg Irrig. Depth - Gopal (cm),
Avg Drying Days Phase 1-4, RL/FL phase Gopal columns

---

Built for AWD Monitoring Programme · Tamil Nadu
