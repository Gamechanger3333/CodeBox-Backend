-- CreateTable
CREATE TABLE "CodeChunk" (
    "id" TEXT NOT NULL,
    "sessionId" TEXT NOT NULL,
    "filePath" TEXT NOT NULL,
    "content" TEXT NOT NULL,
    "embedding" JSONB NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "CodeChunk_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE INDEX "CodeChunk_sessionId_idx" ON "CodeChunk"("sessionId");
