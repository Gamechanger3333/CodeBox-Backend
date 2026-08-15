/*
  Warnings:

  - You are about to drop the `CodeChunk` table. If the table is not empty, all the data it contains will be lost.
  - You are about to drop the `InterviewSession` table. If the table is not empty, all the data it contains will be lost.

*/
-- DropForeignKey
ALTER TABLE "InterviewSession" DROP CONSTRAINT "InterviewSession_projectSessionId_fkey";

-- DropForeignKey
ALTER TABLE "InterviewSession" DROP CONSTRAINT "InterviewSession_userId_fkey";

-- AlterTable
ALTER TABLE "ProjectSession" ADD COLUMN     "ragChunkCount" INTEGER NOT NULL DEFAULT 0,
ADD COLUMN     "ragStatus" TEXT NOT NULL DEFAULT 'pending';

-- DropTable
DROP TABLE "CodeChunk";

-- DropTable
DROP TABLE "InterviewSession";
