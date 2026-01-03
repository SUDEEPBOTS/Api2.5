import os
import uvicorn
import requests
import yt_dlp
import subprocess
from fastapi import FastAPI, BackgroundTasks
from pymongo import MongoClient

# --- CONFIG ---
app = FastAPI(title="Sudeep Music API v2.5", description="Cookies + Aria2 (No Spoofing)")

MONGO_URL = os.getenv("MONGO_URL")
if not MONGO_URL:
    print("⚠️ MONGO_URL Missing")

try:
    client = MongoClient(MONGO_URL)
    db = client["MusicAPI_DB"]
    cache_col = db["songs_cache"]
    print("✅ MongoDB Connected!")
except Exception as e:
    print(f"❌ DB Error: {e}")

CATBOX_URL = "https://catbox.moe/user/api.php"

# --- STARTUP CHECK ---
@app.on_event("startup")
async def check_dependencies():
    print("🚀 STARTING FINAL FIX MODE...")
    
    # FFmpeg Check
    try:
        subprocess.run(["ffmpeg", "-version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        print("✅ FFmpeg Ready")
    except:
        print("❌ FFmpeg Missing (Last buildpack delete kiya kya?)")
    
    # Aria2 Check
    try:
        subprocess.run(["aria2c", "-v"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        print("✅ Aria2c Ready")
    except:
        print("❌ Aria2c Missing")
        
    if os.path.exists("cookies.txt"):
        print("✅ Cookies Found! (Using Browser Identity)")
    else:
        print("⚠️ Cookies Not Found! (Bot Error aa sakta hai)")

# --- BACKGROUND TASK ---
def process_background_download(video_id, title, thumbnail, channel):
    print(f"⏳ TASK START: {title}")
    
    file_name = f"{video_id}.mp3"
    cookie_file = 'cookies.txt' if os.path.exists('cookies.txt') else None

    # 🔥 SETTINGS: Cookies + Aria2 (Simple & Powerful)
    ydl_opts = {
        'format': 'bestaudio[ext=m4a]/bestaudio/best',
        'outtmpl': file_name,
        'quiet': True,
        'geo_bypass': True,
        'nocheckcertificate': True,
        'source_address': '0.0.0.0',
        'cookiefile': cookie_file, # ✅ Asli Cookies use hongi
        'cachedir': False,
        
        # ❌ 'extractor_args' HATA DIYA (Taaki 'Bot Error' na aaye)
        
        # 🚀 ARIA2C ENGINE
        'external_downloader': 'aria2c',
        'external_downloader_args': ['-x', '16', '-s', '16', '-k', '1M'],

        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '64',
        }],
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([f"https://www.youtube.com/watch?v={video_id}"])
        
        if not os.path.exists(file_name):
            raise Exception("Download failed (File not found)")

        print("☁️ Uploading...")
        data = {"reqtype": "fileupload", "userhash": ""}
        catbox_link = None
        
        with open(file_name, "rb") as f:
            files = {"fileToUpload": f}
            response = requests.post(CATBOX_URL, data=data, files=files)
            if response.status_code == 200 and "catbox.moe" in response.text:
                catbox_link = response.text.strip()
        
        if os.path.exists(file_name): os.remove(file_name)

        if not catbox_link:
            raise Exception("Catbox Upload Failed")

        # Success Update
        cache_col.update_one(
            {"video_id": video_id},
            {"$set": {"status": "completed", "catbox_link": catbox_link}}
        )
        print(f"✅ DONE: {catbox_link}")

    except Exception as e:
        print(f"❌ ERROR: {e}")
        if os.path.exists(file_name): os.remove(file_name)
        # Failed Update
        cache_col.update_one(
            {"video_id": video_id},
            {"$set": {"status": "failed", "error_msg": str(e)}}
        )

# --- API ---
@app.get("/")
def home():
    return {"status": "Running", "mode": "Final Fix"}

@app.get("/play")
async def play_song(query: str, background_tasks: BackgroundTasks):
    
    # Search (Simple Settings)
    cookie_file = 'cookies.txt' if os.path.exists('cookies.txt') else None
    ydl_opts_search = {'quiet':True, 'noplaylist':True, 'cookiefile': cookie_file}
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts_search) as ydl:
            if "http" in query: info = ydl.extract_info(query, download=False)
            else: info = ydl.extract_info(f"ytsearch:{query}", download=False)['entries'][0]
            video_id = info['id']
            title = info['title']
    except Exception as e:
        return {"status": "error", "message": f"Search Error: {str(e)}"}

    # Cache Check
    cached_song = cache_col.find_one({"video_id": video_id})
    
    if cached_song:
        status = cached_song.get("status")
        if status == "completed":
            return {"status": "success", "title": cached_song['title'], "url": cached_song['catbox_link']}
        elif status == "processing":
            return {"status": "processing", "message": "Downloading in background..."}
        elif status == "failed":
            # Retry
            cache_col.update_one({"video_id": video_id}, {"$set": {"status": "processing"}})
            background_tasks.add_task(process_background_download, video_id, title, None, None)
            return {"status": "processing", "message": "Retrying failed task..."}

    # New Task
    cache_col.insert_one({"video_id": video_id, "title": title, "status": "processing"})
    background_tasks.add_task(process_background_download, video_id, title, None, None)

    return {"status": "processing", "message": "Started. Check in 30s.", "title": title}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
    
