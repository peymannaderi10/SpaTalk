import { type DailyStats } from "wasp/entities";
import { type CalculateDailyStatsJob } from "wasp/server/jobs";
import { ENTITLING_SUBSCRIPTION_STATUSES } from "../payment/entitlement";
import { paymentProcessor } from "../payment/paymentProcessor";

export type DailyStatsProps = {
  dailyStats?: DailyStats;
  weeklyStats?: DailyStats[];
  isLoading?: boolean;
};

/**
 * Signups, paying clinics and revenue for the agency dashboard. There is no
 * page-view tracking on the portal: the marketing site was removed, and with
 * it the third-party analytics scripts.
 *
 * `paidUserCount` counts *organisations*, not people: a clinic subscribes and
 * may have several people in it (portal plan, Task C6). The column keeps the
 * template's name because open-saas's chart reads it.
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
    // Every status in which the agency is still owed money for the month,
    // including a subscription cancelled but paid to the end of its period.
    const paidUserCount = await context.entities.Organization.count({
      where: {
        subscriptionStatus: { in: [...ENTITLING_SUBSCRIPTION_STATUSES] },
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
