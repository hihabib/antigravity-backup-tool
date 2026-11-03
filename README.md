# Antigravity Backup & Restore CLI Tool 🚀

গুগল এন্টিগ্রাভিটির (Google Antigravity) সমস্ত কনভারসেশন হিস্ট্রি, ব্রেন ডেটা, ট্রান্সক্রিপ্ট, স্কিল, প্লাগইন এবং সেটিংস স্বয়ংক্রিয়ভাবে ব্যাকআপ ও রিস্টোর করার একটি নিরাপদ ও সম্পূর্ণ পাইথন সিএলআই (CLI) টুল।

---

## 🌟 প্রধান সুবিধাসমূহ (Key Features)

1. **নিরাপদ ব্যাকআপ (Safe & Clean Backup):**
   - সব কনভারসেশন ডাটাবেস (`conversations/*.db`), ব্রেন ট্রানস্ক্রিপ্ট (`brain/`), আর্টফ্যাক্টস, কাস্টম স্কিল (`config/skills/`), প্লাগইন এবং রুলস নিখুঁতভাবে কম্প্রেসড জিপ (`.zip`) ফাইলে সেভ করে।
   - অপ্রয়োজনীয় ক্যাশ (`cache/`), ক্র্যাশ ডাম্প (`crashes/`), এবং সাময়িক লগ বাদ দিয়ে ফাইল সাইজ ছোট ও ফাস্ট রাখে।
   - Antigravity অ্যাপ ব্যাকগ্রাউন্ডে চালু থাকলে স্বয়ংক্রিয় ওয়ার্নিং দেয়, যাতে রানিং ডাটাবেস করাপ্ট না হয়।

2. **জিরো-ডেটা-লস সেফটি পয়েন্ট (Pre-Restore Safety Point):**
   - কোনো ব্যাকআপ রিস্টোর করার ঠিক আগে বর্তমান ফাইলের একটি অটোমেটিক সেফটি ব্যাকআপ (`safety_points/`) নিয়ে নেয়। ফলে ভুলবশত রিস্টোর করলেও আগের ডেটা কখনোই হারাবে না!

3. **ইনটেগ্রিটি ও হ্যাশ ভেরিফিকেশন (Integrity Check):**
   - ব্যাকআপ ফাইলের ভেতর `manifest.json` এবং প্রতিটা গুরুত্বপূর্ণ ফাইলের SHA-256 হ্যাশ সংরক্ষণ করে।
   - `verify` কমান্ড দিয়ে ব্যাকআপ ফাইলটি কোনো কারণে নষ্ট বা করাপ্ট হয়েছে কিনা তা রিস্টোর করার আগেই পরীক্ষা করা যায়।

4. **অটোমেটিক সাইডবার ইনডেক্স রিবিল্ড (Auto Sidebar Index Rebuilder):**
   - নতুন কম্পিউটার বা নতুন উইন্ডোজে রিস্টোর করার পর সাইডবারের ইনডেক্স প্রোটোফাইল (`agyhub_summaries_proto.pb`) স্বয়ংক্রিয়ভাবে রিবিল্ড করে দেয়। ফলে ওপেন করলেই সাথে সাথে সমস্ত চ্যাট সাইডবারে দৃশ্যমান হয়।

5. **১-ক্লিক ব্যাচ ফাইল (1-Click Shortcuts):**
   - কোড বা টার্মিনাল না খুলেও শুধুমাত্র ডাবল-ক্লিকে কাজ করার জন্য দুটি রেডিমেড ফাইল দেওয়া আছে।

---

## 📁 ফাইল পরিচিতি

- [`antigravity_backup.py`](file:///C:/Users/Hasib-PC/.gemini/antigravity/scratch/antigravity-backup-tool/antigravity_backup.py) : মূল পাইথন সিএলআই ইঞ্জিন।
- [`1-CLICK-BACKUP.bat`](file:///C:/Users/Hasib-PC/.gemini/antigravity/scratch/antigravity-backup-tool/1-CLICK-BACKUP.bat) : উইন্ডোজে ডাবল-ক্লিক করলেই ব্যাকআপ নেয়ার শর্টকাট।
- [`1-CLICK-RESTORE-LATEST.bat`](file:///C:/Users/Hasib-PC/.gemini/antigravity/scratch/antigravity-backup-tool/1-CLICK-RESTORE-LATEST.bat) : ডাবল-ক্লিক করে কনফার্মেশনের মাধ্যমে লেটেস্ট ব্যাকআপ রিস্টোর করার শর্টকাট।
- [`test_backup_restore.py`](file:///C:/Users/Hasib-PC/.gemini/antigravity/scratch/antigravity-backup-tool/test_backup_restore.py) : সম্পূর্ণ অটোমেটেড ইউনিট ও ইন্টিগ্রেশন টেস্ট স্যুট (১০০% পাসড)।

---

## 🛠️ সিএলআই কমান্ডসমূহ (CLI Usage)

টার্মিনাল থেকে স্ক্রিপ্টটি চালানোর বিভিন্ন নিয়ম:

### ১. ব্যাকআপ তৈরি করা (Backup)
```bash
# সাধারণ ব্যাকআপ (ডিফল্ট: ~/AntigravityBackups ফোল্ডারে জিপ তৈরি হবে)
python antigravity_backup.py backup

# নির্দিষ্ট কোনো ফোল্ডারে ব্যাকআপ নিতে চাইলে (যেমন D:\MyBackups)
python antigravity_backup.py backup --dest "D:\MyBackups"

# ব্যাকআপের সাথে একটি ট্যাগ বা লেবেল যুক্ত করতে চাইলে
python antigravity_backup.py backup --tag "before_os_reinstall"
```

### ২. ব্যাকআপের তালিকা দেখা (List Backups)
```bash
python antigravity_backup.py list
```
*(এটি আগের সমস্ত ব্যাকআপের তারিখ, ফাইল সাইজ এবং কতটি কনভারসেশন আছে তা একটি টেবিলে দেখাবে।)*

### ৩. ব্যাকআপ পরীক্ষা ও বিস্তারিত দেখা (Inspect & Read Backup)
```bash
# রিস্টোর না করেই ব্যাকআপের ভেতরে কি কি আছে, স্কিল, প্লাগইন, চ্যাটের নাম ইত্যাদি দেখা:
python antigravity_backup.py inspect --file "C:\Users\Hasib-PC\AntigravityBackups\antigravity_backup_20261011_171500.zip"
```

### ৪. ব্যাকআপের সুস্থতা যাচাই (Verify Integrity)
```bash
python antigravity_backup.py verify --file "C:\Users\Hasib-PC\AntigravityBackups\antigravity_backup_20261011_171500.zip"
```

### ৫. ডেটা রিস্টোর করা (Restore)
```bash
# সবচেয়ে সাম্প্রতিক (Latest) ব্যাকআপটি রিস্টোর করতে:
python antigravity_backup.py restore --latest

# নির্দিষ্ট কোনো ব্যাকআপ ফাইল থেকে রিস্টোর করতে:
python antigravity_backup.py restore --file "D:\MyBackups\antigravity_backup_20261011_171500.zip"
```

### ৬. শুধুমাত্র সাইডবার ইনডেক্স রিবিল্ড করা (Rebuild Sidebar Index)
```bash
python antigravity_backup.py rebuild-index
```

---

## 🧪 টেস্ট চালানোর নিয়ম (Run Automated Tests)

আমরা একটি সম্পূর্ণ আইসোলেটেড মক এনভায়রনমেন্ট তৈরি করে টেস্টগুলো ভেরিফাই করেছি:
```bash
python test_backup_restore.py -v
```
**টেস্টে যা যা যাচাই করা হয়:**
- ✅ ব্যাকআপ ঠিকমতো জিপ হচ্ছে কিনা এবং অপ্রয়োজনীয় ক্যাশ ফাইল বাদ পড়ছে কিনা।
- ✅ ম্যানিফেস্ট ও SHA-256 ফাইল হ্যাশ নিখুঁতভাবে তৈরি হচ্ছে কিনা।
- ✅ করাপ্ট বা বিকৃত ব্যাকআপ ফাইল ডিটেক্ট করে আটকে দেওয়া হচ্ছে কিনা।
- ✅ রিস্টোরের আগে স্বয়ংক্রিয় সেফটি পয়েন্ট তৈরি হচ্ছে কিনা।
- ✅ নতুন ফোল্ডারে ফাইলগুলো হুবহু এক্সট্র্যাক্ট হচ্ছে কিনা।
- ✅ সাইডবার ইনডেক্স প্রোটোফাইল সঠিকভাবে তৈরি হচ্ছে কিনা।
