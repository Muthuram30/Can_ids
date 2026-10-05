# GitHub Setup Guide

## Repository Information

**GitHub Repository**: https://github.com/Muthuram30/Can_ids.git  
**Branch**: main  
**Owner**: Muthuram30

---

## Step-by-Step GitHub Push Instructions

### 1. Extract the Repository

First, extract the `car-ids-hil-github-ready.zip` to your desired location.

### 2. Initialize Git Repository

Open a terminal/command prompt in the extracted `car-ids-hil` directory:

```bash
cd car-ids-hil
git init
```

### 3. Add All Files

```bash
git add .
```

### 4. Create Initial Commit

```bash
git commit -m "Initial commit: CAN IDS HIL Project

- Complete working IDS with ML (Isolation Forest + Random Forest)
- Modular architecture for extensibility
- ESP32 firmware for Motor, Sensor, and Security ECUs
- Comprehensive documentation with hardware photos
- Configuration management via .env
- USB attack demonstration
- Network monitoring and isolation
- Professional GitHub-ready structure"
```

### 5. Add Remote Repository

```bash
git remote add origin https://github.com/Muthuram30/Can_ids.git
```

### 6. Rename Branch to Main

```bash
git branch -M main
```

### 7. Push to GitHub

```bash
git push -u origin main
```

If the repository already has content and you want to force push (⚠️ **WARNING: This will overwrite existing content**):

```bash
git push -u origin main --force
```

---

## Alternative: Using GitHub Desktop

1. Open GitHub Desktop
2. File → Add Local Repository
3. Choose the `car-ids-hil` folder
4. Click "Publish repository"
5. Select your account (Muthuram30)
6. Repository name: `Can_ids`
7. Click "Publish Repository"

---

## Verify Upload

After pushing, verify on GitHub:
- Visit: https://github.com/Muthuram30/Can_ids
- Check that all files are present
- Verify images are displaying in README.md
- Review the rendered documentation

---

## Troubleshooting

### Authentication Issues

If you encounter authentication errors:

**Using Personal Access Token (PAT)**:
1. Go to GitHub Settings → Developer settings → Personal access tokens
2. Generate new token (classic)
3. Select scopes: `repo` (all)
4. Copy the token
5. When prompted for password, use the token instead

**Using SSH**:
```bash
# Add SSH remote instead
git remote remove origin
git remote add origin git@github.com:Muthuram30/Can_ids.git
git push -u origin main
```

### Large File Issues

If you get errors about large files:
```bash
# Check file sizes
find . -type f -size +50M

# Consider using Git LFS for large files
git lfs install
git lfs track "*.mp4"
git lfs track "*.jpeg"
git add .gitattributes
git commit -m "Add Git LFS tracking"
git push
```

### Repository Already Exists

If the repository already has content:

**Option 1: Pull first, then push**
```bash
git pull origin main --allow-unrelated-histories
git push -u origin main
```

**Option 2: Force push (⚠️ destroys existing content)**
```bash
git push -u origin main --force
```

---

## Post-Push Checklist

After successfully pushing to GitHub:

- [ ] ✅ README.md displays correctly with images
- [ ] ✅ Hardware photos are visible
- [ ] ✅ LICENSE file is present
- [ ] ✅ .gitignore is working (no .env, .pyc, etc.)
- [ ] ✅ All documentation files are present
- [ ] ✅ ESP32 firmware files are included
- [ ] ✅ Python modules are properly structured
- [ ] ✅ Scripts have proper line endings
- [ ] ✅ Google Drive link is clickable

---

## Repository Settings (Optional)

### Add Topics

On GitHub repository page:
1. Click "⚙️ Settings" → About → Topics
2. Add relevant topics:
   - `automotive-security`
   - `can-bus`
   - `intrusion-detection`
   - `machine-learning`
   - `raspberry-pi`
   - `esp32`
   - `cybersecurity`
   - `hil-testing`
   - `isolation-forest`
   - `random-forest`

### Configure Pages (for documentation)

1. Settings → Pages
2. Source: Deploy from a branch
3. Branch: main, folder: /docs
4. Save

### Add Description

Add a concise description:
```
Real-time CAN bus intrusion detection using ML on Raspberry Pi 5. Multi-ECU HIL testbed with Isolation Forest & Random Forest models for automotive cybersecurity research.
```

### Add Website URL

Link to Google Drive or GitHub Pages if enabled.

---

## Keeping Repository Updated

### Future Updates

```bash
# Make changes to files
git add .
git commit -m "Description of changes"
git push origin main
```

### Creating Releases

When ready for a release:
1. Go to repository → Releases → Create new release
2. Tag: v1.0.0
3. Title: "CAN IDS HIL v1.0.0 - Initial Release"
4. Description: Summarize features
5. Attach `car-ids-hil-github-ready.zip` as release asset
6. Publish release

---

## Quick Reference

```bash
# Clone the repository elsewhere
git clone https://github.com/Muthuram30/Can_ids.git

# Pull latest changes
git pull origin main

# Check status
git status

# View commit history
git log --oneline

# Create a new branch for features
git checkout -b feature-name
git push -u origin feature-name
```

---

**Need Help?**
- GitHub Docs: https://docs.github.com
- Git Basics: https://git-scm.com/book/en/v2
- Contact: Muthuraman M (Repository Maintainer)
