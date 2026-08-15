-- CreateTable: InterviewSession
-- Mock technical interview grounded in the user's currently uploaded
-- project (ProjectSession). One per user. Re-uploading a project deletes
-- the old InterviewSession via ON DELETE CASCADE on projectSessionId,
-- since old questions would reference files that no longer exist.

CREATE TABLE "InterviewSession" (
  "id"               TEXT NOT NULL,
  "userId"           INTEGER NOT NULL,
  "projectSessionId" TEXT NOT NULL,
  "questions"        TEXT NOT NULL,             -- JSON array of { id, category, question }
  "transcript"       TEXT NOT NULL DEFAULT '[]', -- JSON array of { questionId, question, answer, feedback }
  "currentIndex"     INTEGER NOT NULL DEFAULT 0,
  "status"           TEXT NOT NULL DEFAULT 'in_progress', -- 'in_progress' | 'completed'
  "report"           TEXT,                       -- final weakness report (set when completed)
  "createdAt"        TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  "updatedAt"        TIMESTAMP(3) NOT NULL,

  CONSTRAINT "InterviewSession_pkey" PRIMARY KEY ("id")
);

-- One interview session per user
CREATE UNIQUE INDEX "InterviewSession_userId_key" ON "InterviewSession"("userId");

-- One interview session per project session (1:1)
CREATE UNIQUE INDEX "InterviewSession_projectSessionId_key" ON "InterviewSession"("projectSessionId");

-- Foreign key to User
ALTER TABLE "InterviewSession"
  ADD CONSTRAINT "InterviewSession_userId_fkey"
  FOREIGN KEY ("userId") REFERENCES "User"("id")
  ON DELETE CASCADE ON UPDATE CASCADE;

-- Foreign key to ProjectSession — deleting/replacing the project session
-- cascades to delete the interview session tied to it.
ALTER TABLE "InterviewSession"
  ADD CONSTRAINT "InterviewSession_projectSessionId_fkey"
  FOREIGN KEY ("projectSessionId") REFERENCES "ProjectSession"("id")
  ON DELETE CASCADE ON UPDATE CASCADE;
