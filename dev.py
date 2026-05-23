import os
import sys
import time
import subprocess

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
except ImportError:
    print("[DEV ERROR] Module 'watchdog' belum terinstall.")
    print("Silakan jalankan perintah ini di terminal:")
    print("pip install watchdog")
    sys.exit(1)

class RestartHandler(FileSystemEventHandler):
    def __init__(self, restart_func):
        super().__init__()
        self.restart_func = restart_func
        self.last_restart = time.time()

    def on_any_event(self, event):
        if event.is_directory:
            return
            
        # Hanya memantau file berakhiran .py atau .env
        if event.src_path.endswith('.py') or event.src_path.endswith('.env'):
            # Menghindari restart berkali-kali dalam waktu yang sangat singkat (debounce 2 detik)
            if time.time() - self.last_restart > 2.0:
                print(f"\n[DEV] Perubahan terdeteksi pada: {os.path.basename(event.src_path)}")
                self.last_restart = time.time()
                self.restart_func()

def run_main():
    print("[DEV] Memulai main.py...")
    # Menjalankan main.py dengan proses python saat ini (sys.executable)
    return subprocess.Popen([sys.executable, "main.py"])

def start_dev_server():
    process = run_main()

    def restart():
        nonlocal process
        print("[DEV] Menghentikan proses yang sedang berjalan...")
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill() # Paksa berhenti jika nyangkut
        process = run_main()

    event_handler = RestartHandler(restart)
    observer = Observer()
    
    # Memantau seluruh folder tempat dev.py berada beserta sub-foldernya (recursive=True)
    path = os.path.dirname(os.path.abspath(__file__))
    observer.schedule(event_handler, path, recursive=True)
    
    print(f"[DEV] Sistem Auto-Reload aktif.")
    print(f"[DEV] Menunggu perubahan file di project Anda...")
    observer.start()
    
    try:
        while True:
            time.sleep(1)
            # Jika main.py crash, dev.py akan tetap hidup dan menunggu Anda memperbaiki kode
    except KeyboardInterrupt:
        print("\n[DEV] Mematikan auto-reload...")
        observer.stop()
        process.terminate()
        process.wait()
    
    observer.join()

if __name__ == "__main__":
    start_dev_server()
