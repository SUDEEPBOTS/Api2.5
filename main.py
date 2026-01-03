import os
import uvicorn
import requests
import yt_dlp
import subprocess
from fastapi import FastAPI
from pymongo import MongoClient

# --- CONFIG ---
app = FastAPI(title="Sudeep Music API v2.5", description="Public Mode Music API")

# MongoDB Connect
MONGO_URL = os.getenv("MONGO_URL")
if not MONGO_URL:
    print("⚠️ WARNING: MONGO_URL nahi mila! Config check kar.")

try:
    client = MongoClient(MONGO_URL)
    db = client["MusicAPI_DB"]
    cache_col = db["songs_cache"]
    print("✅ MongoDB Connected!")
except Exception as e:
    print(f"❌ DB Error: {e}")

# Catbox API
CATBOX_URL = "https://catbox.moe/user/api.php"

# --- SYSTEM CHECK ON STARTUP ---
@app.on_event("startup")
async def check_dependencies():
    print("\n" + "="*40)
    print("🚀 STARTING PUBLIC MODE CHECKS...")
    
    # 1. Check FFmpeg
    try:
        subprocess.run(["ffmpeg", "-version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        print("✅ FFmpeg is Installed & Running!")
    except Exception:
        print("❌ CRITICAL: FFmpeg nahi mila! Buildpack check karo.")

    # 2. Check Node.js
    try:
        subprocess.run(["node", "-v"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        print("✅ Node.js is Installed & Running!")
    except Exception:
        print("❌ WARNING: Node.js nahi mila!")
    
    # Cookies check (Sirf info ke liye)
    if os.path.exists("cookies.txt"):
        print("⚠️ NOTE: cookies.txt abhi bhi hai, par hum use nahi karenge.")
    else:
        print("✅ Public Mode Active: No cookies found (Safe & Fast)")
    
    print("="*40 + "\n")

# --- HELPER: UPLOAD ---
def upload_to_catbox(file_path):
    try:
        data = {"reqtype": "fileupload", "userhash": ""}
        with open(file_path, "rb") as f:
            files = {"fileToUpload": f}
            response = requests.post(CATBOX_URL, data=data, files=files)
        
        if response.status_code == 200 and "catbox.moe" in response.text:
            return response.text.strip()
        else:
            return None
    except Exception as e:
        print(f"Upload Error: {e}")
        return None

# --- API ENDPOINT ---
@app.get("/")
def home():
    return {"status": "Running", "mode": "Public (No Cookies)", "version": "2.5"}

@app.get("/play")
async def play_song(query: str):
    
    # --- STEP 1: SEARCH ---
    print(f"🔎 Searching: {query}")
    
    # 🔥 PUBLIC MODE SEARCH SETTINGS
    ydl_opts_search = {
        'quiet': True, 
        'noplaylist': True, 
        'check_formats': False,
        'cachedir': False  # Cache Disable
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts_search) as ydl:
            if "http" in query:
                info = ydl.extract_info(query, download=False)
            else:
                info = ydl.extract_info(f"ytsearch:{query}", download=False)['entries'][0]
            
            video_id = info['id']
            title = info['title']
            duration = info.get('duration_string', 'Unknown')
            thumbnail = info.get('thumbnail')
            channel = info.get('uploader')
            views = info.get('view_count')
            
    except Exception as e:
        return {"status": "error", "message": f"Song nahi mila: {str(e)}"}

    # --- STEP 2: CACHE CHECK ---
    cached_song = cache_col.find_one({"video_id": video_id})
    if cached_song:
        print(f"🚀 Cache Hit: {title}")
        return {
            "status": "success",
            "source": "database (Ultra Fast)",
            "title": cached_song['title'],
            "url": cached_song['catbox_link'],
            "thumbnail": cached_song.get('thumbnail', thumbnail),
            "duration": duration,
            "channel": channel,
            "views": views,
            "video_id": video_id
        }

    # --- STEP 3: DOWNLOAD & UPLOAD ---
    print(f"⬇️ Downloading New: {title}")
    
    file_name = f"{video_id}.mp3"
    
    # 🔥 UPDATED SETTINGS (PUBLIC MODE + FAST SPEED)
    ydl_opts_down = {
        'format': 'bestaudio/best',
        'outtmpl': file_name,
        'quiet': True,
        'geo_bypass': True,
        'nocheckcertificate': True,
        
        # 🔥 MAIN CHANGES FOR HEROKU
        'cachedir': False,            # Purana cache clear rakhne ke liye
        'source_address': '0.0.0.0',  # Connection stability ke liye
        'check_formats': False,       # Warning kam karne ke liye
        
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '128',
        }],
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts_down) as ydl:
            ydl.download([f"https://www.youtube.com/watch?v={video_id}"])
        
        if not os.path.exists(file_name):
             return {"status": "error", "message": "Download failed (File not created)"}

        print("☁️ Uploading to Catbox...")
        catbox_link = upload_to_catbox(file_name)
        
        if os.path.exists(file_name):
            os.remove(file_name)

        if not catbox_link:
             return {"status": "error", "message": "Catbox upload failed"}

        # --- STEP 4: SAVE TO DB ---
        cache_col.insert_one({
            "video_id": video_id,
            "title": title,
            "catbox_link": catbox_link,
            "thumbnail": thumbnail,
            "channel": channel,
            "created_at": "v2.5 Public"
        })
        print("✅ Saved to DB!")

        return {
            "status": "success",
            "source": "live_processed",
            "title": title,
            "url": catbox_link,
            "thumbnail": thumbnail,
            "duration": duration,
            "channel": channel,
            "views": views,
            "video_id": video_id
        }

    except Exception as e:
        if os.path.exists(file_name): os.remove(file_name)
        return {"status": "error", "message": str(e)}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
    
