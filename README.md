# Video Shop

A simple site where you upload your own videos, visitors see them as thumbnails, tap Download, get shown your Till number, pay, and the download unlocks once you approve the payment.

## Try it on your computer (5 minutes)

1. Install Python 3.10 or newer from python.org.
2. Open a terminal in this folder and run:

   ```
   pip install -r requirements.txt
   ```

3. Start the site (pick your own admin password):

   - Windows (PowerShell):
     ```
     $env:ADMIN_PASSWORD="choose-a-password"; $env:TILL_NUMBER="5196055"; python app.py
     ```
   - Mac / Linux:
     ```
     ADMIN_PASSWORD=choose-a-password TILL_NUMBER=5196055 python app.py
     ```

4. Open http://localhost:8000 for the shop and http://localhost:8000/admin for your admin pages.

## How you use it

1. **Add videos:** Admin → Videos. Enter a title, pick Movie, Series or Video, set the price, choose the file. A thumbnail is taken from the video automatically, or you can upload your own picture. For a series with many episodes, put them in one .zip file.
2. **A visitor taps Download:** they enter their M-Pesa number, then see the Till number and the amount.
3. **You approve:** Admin → Payments shows the request with the phone number and amount. Check your M-Pesa SMS for the same number and amount, then tap Approve.
4. **Their page unlocks by itself** within a few seconds and shows the Download button. The link works for 72 hours.

## Switching to your brother's Till

Change `TILL_NUMBER` when you start the site. Nothing else needs editing.

## Settings (all optional, set like TILL_NUMBER)

| Name | Default | What it does |
|---|---|---|
| `TILL_NUMBER` | 5196055 | Till shown to customers |
| `ADMIN_PASSWORD` | none | Required. Without it, admin login is off |
| `SITE_NAME` | VillageFlix | Name at the top of the site |
| `LINK_HOURS` | 72 | How long a paid download stays open |
| `MAX_UPLOAD_GB` | 4 | Biggest file you can upload |
| `PORT` | 8000 | Port the site runs on |
| `DATA_DIR` | `./data` | Where videos, thumbnails and the database are kept |

## Putting it online for the village

Running it on a home computer only works while that computer is on and connected. For people in Matsangoni to use it any time, put it on a small rented server (a VPS or any host that can run Python), then run it with:

```
pip install gunicorn
ADMIN_PASSWORD=... TILL_NUMBER=... gunicorn -w 2 --threads 4 --timeout 3600 -b 0.0.0.0:8000 app:app
```

If you put a web server such as nginx in front, raise its upload size limit and timeouts, or large uploads will fail. Set `HTTPS=1` once the site is served over HTTPS.

Back up the `data` folder. It holds everything.

## Things to know

- Approval is manual, as you asked. Nobody can download without you tapping Approve.
- Anyone with a paid link can use it until it expires, so the link can be shared. Keep the time short if that worries you.
- Movies are big files. Downloads use the customer's mobile data, so keep file sizes reasonable.
- Only upload videos you made or have the right to sell.

## Client jobs (your own videography work)

This is for finished work you made for a client. The client pays, then the download appears on their own page.

1. Upload the finished video to Google Drive. Share it as **Anyone with the link** and copy the link.
2. Log in to the admin page and open **Client jobs**. Enter the title, client name, price and the Drive link, then tap **Create client link**.
3. Tap **Send on WhatsApp** (or **Copy link**) and send the client their private page.
4. The client sees your till number and the amount. After paying, they enter their M-Pesa number and tap **I have paid**.
5. The job moves to the top of your list as **Says paid**. Check your M-Pesa message, then tap **Mark as paid**.
6. The client's page updates by itself and shows a **Download your video** button.

The Drive link is kept on the server. It is never in the page the client sees until you mark the job paid, and the Download button opens it for them. A client who is sent the link can still pass the Drive file on, so use **Lock again** if you need to stop it for new people. Deleting the Drive file or turning off its sharing stops the old link.

## Putting it online (PythonAnywhere, free plan)

This site needs a server that runs Python. GitHub Pages cannot run it. PythonAnywhere has a free plan that works for client jobs, where the videos stay on Google Drive. For uploading big files straight to the site, use a paid server instead.

1. Make an account at pythonanywhere.com. Your site will be `yourusername.pythonanywhere.com`.
2. Open **Files**, upload `video-shop.zip`, then open a **Bash console** and run: `unzip video-shop.zip`
3. Open **Web**, then **Add a new web app**, choose **Manual configuration** and a recent Python 3 version.
4. On the Web page, open the **WSGI configuration file** and replace everything in it with this (change `yourusername` and the password):

```
import sys, os
path = '/home/yourusername/video-shop'
if path not in sys.path:
    sys.path.insert(0, path)
os.environ['ADMIN_PASSWORD'] = 'choose-a-strong-password'
os.environ['TILL_NUMBER'] = '5196055'
os.environ['SITE_NAME'] = 'VillageFlix'
os.environ['DATA_DIR'] = '/home/yourusername/video-shop-data'
os.environ['HTTPS'] = '1'
from app import app as application
```

5. Press **Reload** on the Web page. Open `https://yourusername.pythonanywhere.com/admin` and log in.

PythonAnywhere may ask you now and then to press a button to keep a free web app running. Check their pages for the current rules.
