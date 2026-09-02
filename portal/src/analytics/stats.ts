import { type DailyStats } from "wasp/entities";
import { type CalculateDailyStatsJob } from "wasp/server/jobs";
import { paymentProcessor } from "../payment/paymentProcessor";
import { SubscriptionStatus } from "../payment/plans";

export type DailyStatsProps = {
  dailyStats?: DailyStats;
  weeklyStats?: DailyStats[];
  isLoading?: boolean;
};

/**
 * Signups, paying customers and revenue for the agency dashboard. There is no
 * page-view tracking on the portal: the marketing site was removed, and with
 * it the third-party analytics scripts.
 */
export const calculateDailyStatsJob: CalculateDailyStatsJob<
  never,
  void
> = async (_args, context) => {
  const nowUTC = new Date(Date.now());
  nowUTC.setUTCHours(0, 0, 0, 0);

  const yesterdayUTC = new Date(nowUTC);
  yesterdayUTC.setUTCDate(yesterdayUTC.getUTCDate() - 1);

  try {
    const yesterdaysStats = await context.entities.DailyStats.findFirst({
      where: {
        date: {
          equals: yesterdayUTC,
        },
      },
    });

    const userCount = await context.entities.User.count({});
    // Users can have paid but canceled subscriptions which terminate at the end
    // of the period; those are not current paying users.
    const paidUserCount = await context.entities.User.count({
      where: {
        subscriptionStatus: SubscriptionStatus.Active,
      },
    });

    let userDelta = userCount;
    let paidUserDelta = paidUserCount;
    if (yesterdaysStats) {
      userDelta -= yesterdaysStats.userCount;
      paidUserDelta -= yesterdaysStats.paidUserCount;
    }

    const totalRevenue = await paymentProcessor.fetchTotalRevenue();

    await context.entities.DailyStats.upsert({
      where: {
        date: nowUTC,
      },
      create: {
        date: nowUTC,
        userCount,
        paidUserCount,
        userDelta,
        paidUserDelta,
        totalRevenue,
      },
      update: {
        userCount,
        paidUserCount,
        userDelta,
        paidUserDelta,
        totalRevenue,
      },
    });
  } catch (error) {
    console.error("Error calculating daily stats: ", error);
    await context.entities.Logs.create({
      data: {
        message: `Error calculating daily stats: ${error instanceof Error ? error.message : String(error)}`,
        level: "job-error",
      },
    });
  }
};
