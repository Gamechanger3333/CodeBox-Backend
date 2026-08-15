-- CreateTable
CREATE TABLE "IngestedFileHash" (
    "id" TEXT NOT NULL,
    "sessionId" TEXT NOT NULL,
    "filePath" TEXT NOT NULL,
    "contentHash" TEXT NOT NULL,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "IngestedFileHash_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE INDEX "IngestedFileHash_sessionId_idx" ON "IngestedFileHash"("sessionId");

-- CreateIndex
CREATE UNIQUE INDEX "IngestedFileHash_sessionId_filePath_key" ON "IngestedFileHash"("sessionId", "filePath");
