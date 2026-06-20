-- CreateTable: ProjectSession
-- Stores extracted project files + analysis per user in the database
-- so the project survives server restarts (replaces the in-memory Map).

CREATE TABLE "ProjectSession" (
  "id"          TEXT NOT NULL,
  "userId"      INTEGER NOT NULL,
  "projectName" TEXT NOT NULL,
  "fileTree"    TEXT NOT NULL,
  "files"       TEXT NOT NULL,   -- JSON array of { path, content }
  "stats"       TEXT NOT NULL,   -- JSON object  { total, analyzed, skipped, totalChars }
  "analysis"    TEXT NOT NULL,   -- The initial AI analysis text
  "history"     TEXT NOT NULL DEFAULT '[]', -- JSON array of { role, content }
  "createdAt"   TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  "updatedAt"   TIMESTAMP(3) NOT NULL,

  CONSTRAINT "ProjectSession_pkey" PRIMARY KEY ("id")
);

-- One session per user (upsert on upload)
CREATE UNIQUE INDEX "ProjectSession_userId_key" ON "ProjectSession"("userId");

-- Foreign key to User
ALTER TABLE "ProjectSession"
  ADD CONSTRAINT "ProjectSession_userId_fkey"
  FOREIGN KEY ("userId") REFERENCES "User"("id")
  ON DELETE CASCADE ON UPDATE CASCADE;