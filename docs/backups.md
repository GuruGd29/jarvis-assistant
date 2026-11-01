# Encrypted backups

`bin/backup.sh` backs up everything Jarvis knows (the database, Hermes's memory and chats, your settings and
sign-ins, and `~/Jarvis`) with [restic](https://restic.net), which **encrypts on your machine** before anything
is uploaded. It keeps 7 daily, 4 weekly and 6 monthly snapshots, runs every night at 3:00, and stays quiet unless
something fails.

Any storage restic supports works. These steps use Oracle Object Storage, which is free up to 20 GB.

## 1. A bucket and a key

In the Oracle Console:

1. **Storage → Buckets → Create bucket**, for example `jarvis-backup` (Standard tier, private).
2. Note your **namespace** (shown on the bucket page) and your **region** identifier (for example `ap-mumbai-1`).
3. **Profile (top right) → User settings → Customer secret keys → Generate secret key.** Copy both the access key
   and the secret; the secret is shown only once.

## 2. Settings

Create `~/jarvis-system/secrets/backup.env` (keep it private: `chmod 600`):

```bash
RESTIC_REPOSITORY=s3:https://NAMESPACE.compat.objectstorage.REGION.oraclecloud.com/jarvis-backup
AWS_ACCESS_KEY_ID=the-access-key
AWS_SECRET_ACCESS_KEY=the-secret
AWS_DEFAULT_REGION=REGION
```

## 3. Start

```bash
cd ~/jarvis-system
bin/backup.sh init    # creates secrets/restic-password and the encrypted repository
bin/backup.sh         # the first backup
bin/add-jobs.sh       # adds the nightly 3:00 job now that backups are set up
```

**Save `secrets/restic-password` in your password manager now.** Without it the backups can't be read by anyone,
including you. It's deliberately left out of the backups themselves.

## Restore

```bash
set -a; . ~/jarvis-system/secrets/backup.env; set +a
export RESTIC_PASSWORD_FILE=~/jarvis-system/secrets/restic-password   # or type it when asked
restic snapshots                                  # what's there
restic restore latest --target ~/jarvis-restore   # everything, into a separate folder
```

Copy back what you need from `~/jarvis-restore`. The database is the file `jarvis-db.dump`
(`find ~/jarvis-restore -name jarvis-db.dump`); load it into an empty `jarvis` database with:

```bash
pg_restore -h 127.0.0.1 -U jarvis -d jarvis --clean --if-exists path/to/jarvis-db.dump
```

Try a restore once after setting this up, so you know it works before you need it.
