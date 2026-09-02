/*
  Warnings:

  - You are about to drop the column `datePaid` on the `User` table. All the data in the column will be lost.
  - You are about to drop the column `paymentProcessorUserId` on the `User` table. All the data in the column will be lost.
  - You are about to drop the column `subscriptionPlan` on the `User` table. All the data in the column will be lost.
  - You are about to drop the column `subscriptionStatus` on the `User` table. All the data in the column will be lost.

*/
-- DropIndex
DROP INDEX "User_paymentProcessorUserId_key";

-- AlterTable
ALTER TABLE "User" DROP COLUMN "datePaid",
DROP COLUMN "paymentProcessorUserId",
DROP COLUMN "subscriptionPlan",
DROP COLUMN "subscriptionStatus";
