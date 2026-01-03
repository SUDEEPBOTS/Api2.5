import os
import uvicorn
import requests
import yt_dlp
from fastapi import FastAPI
from pymongo import MongoClient

# --- CONFIG ---
app = FastAPI(title="Sudeep Music API v2.5", description="Ultra Fast Cached Music API")

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

# --- HELPER: UPLOAD TO CATBOX ---
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
    return {"status": "Running", "creator": "Sudeep", "version": "2.5 (Super Light)"}

@app.get("/play")
async def play_song(query: str):
    """
    Logic: 
    1. YouTube ID Nikalo 
    2. DB Check Karo 
    3. Download -> Upload -> Save
    """
    
    # --- STEP 1: SEARCH & GET INFO ---
    print(f"🔎 Searching: {query}")
    
    # Cookies check
    cookie_file = 'cookies.txt' if os.path.exists('cookies.txt') else None

    # Search Options
    ydl_opts_search = {
        'quiet': True, 
        'noplaylist': True, 
        'cookiefile': cookie_file,
        'check_formats': False # 🔥 Fix for Warnings
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts_search) as ydl:
            if "http" in query:
                info = ydl.extract_info(query, download=False)
            else:
                # Search karo aur pehla result lo
                info = ydl.extract_info(f"ytsearch:{query}", download=False)['entries'][0]
            
            # Data Extraction
            video_id = info['id']
            title = info['title']
            duration = info.get('duration_string', 'Unknown')
            thumbnail = info.get('thumbnail')
            channel = info.get('uploader')
            views = info.get('view_count')
            
    except Exception as e:
        return {"status": "error", "message": f"Song nahi mila: {str(e)}"}

    # --- STEP 2: CACHE CHECK (DATABASE) ---
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

    # --- STEP 3: DOWNLOAD & UPLOAD (NEW SONG) ---
    print(f"⬇️ Downloading New: {title}")
    
    file_name = f"{video_id}.mp3"
    
    # 🔥 UPDATED SETTINGS (Size aur Speed ke liye)
    ydl_opts_down = {
        'format': 'bestaudio/best',
        'outtmpl': file_name,
        'quiet': True,
        'cookiefile': cookie_file,
        'geo_bypass': True,
        'nocheckcertificate': True,
        'check_formats': False, # 🔥 WARNING FIX
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '128', # 🔥 128kbps (Best balance for Telegram)
        }],
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts_down) as ydl:
            # Direct ID se download fast hota hai
            ydl.download([f"https://www.youtube.com/watch?v={video_id}"])
        
        # Verify File
        if not os.path.exists(file_name):
             return {"status": "error", "message": "Download failed"}

        # Upload
        print("☁️ Uploading to Catbox...")
        catbox_link = upload_to_catbox(file_name)
        
        # Cleanup (Local file delete)
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
            "created_at": "v2.5"
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
    
