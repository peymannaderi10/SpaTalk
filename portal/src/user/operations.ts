import { type Prisma } from "@prisma/client";
import { type User } from "wasp/entities";
import { HttpError, prisma } from "wasp/server";
import {
  type GetPaginatedUsers,
  type UpdateIsUserAdminById,
} from "wasp/server/operations";
import * as z from "zod";
import { type OrgRole } from "../organizations/roles";
import { ensureArgsSchemaOrThrowHttpError } from "../server/validation";

const updateUserAdminByIdInputSchema = z.object({
  id: z.string().nonempty(),
  isAdmin: z.boolean(),
});

type UpdateUserAdminByIdInput = z.infer<typeof updateUserAdminByIdInputSchema>;

export const updateIsUserAdminById: UpdateIsUserAdminById<
  UpdateUserAdminByIdInput,
  User
> = async (rawArgs, context) => {
  const { id, isAdmin } = ensureArgsSchemaOrThrowHttpError(
    updateUserAdminByIdInputSchema,
    rawArgs,
  );

  if (!context.user) {
    throw new HttpError(
      401,
      "Only authenticated users are allowed to perform this operation",
    );
  }

  if (!context.user.isAdmin) {
    throw new HttpError(
      403,
      "Only admins are allowed to perform this operation",
    );
  }

  return context.entities.User.update({
    where: { id },
    data: { isAdmin },
  });
};

/**
 * The agency's list of people. A person has no subscription — a clinic does
 * (portal plan, Task C6) — so what an admin needs beside a name is which
 * organisations that person can open, and as what.
 */
type GetPaginatedUsersOutput = {
  users: (Pick<User, "id" | "email" | "username" | "isAdmin"> & {
    organizations: { id: string; name: string; slug: string; role: OrgRole }[];
  })[];
  totalPages: number;
};

const getPaginatorArgsSchema = z.object({
  skipPages: z.number(),
  filter: z.object({
    emailContains: z.string().nonempty().optional(),
    isAdmin: z.boolean().optional(),
  }),
});

type GetPaginatedUsersInput = z.infer<typeof getPaginatorArgsSchema>;

export const getPaginatedUsers: GetPaginatedUsers<
  GetPaginatedUsersInput,
  GetPaginatedUsersOutput
> = async (rawArgs, context) => {
  if (!context.user) {
    throw new HttpError(
      401,
      "Only authenticated users are allowed to perform this operation",
    );
  }

  if (!context.user.isAdmin) {
    throw new HttpError(
      403,
      "Only admins are allowed to perform this operation",
    );
  }

  const {
    skipPages,
    filter: { emailContains, isAdmin },
  } = ensureArgsSchemaOrThrowHttpError(getPaginatorArgsSchema, rawArgs);

  const pageSize = 10;

  const where: Prisma.UserWhereInput = {
    email: {
      contains: emailContains,
      mode: "insensitive",
    },
    isAdmin,
  };

  const [pageOfUsers, totalUsers] = await prisma.$transaction([
    context.entities.User.findMany({
      skip: skipPages * pageSize,
      take: pageSize,
      where,
      select: {
        id: true,
        email: true,
        username: true,
        isAdmin: true,
        memberships: {
          select: {
            role: true,
            organization: { select: { id: true, name: true, slug: true } },
          },
          orderBy: { createdAt: "asc" },
        },
      },
      orderBy: { email: "asc" },
    }),
    context.entities.User.count({ where }),
  ]);

  return {
    users: pageOfUsers.map((user) => ({
      id: user.id,
      email: user.email,
      username: user.username,
      isAdmin: user.isAdmin,
      organizations: user.memberships.map((membership) => ({
        id: membership.organization.id,
        name: membership.organization.name,
        slug: membership.organization.slug,
        role: membership.role,
      })),
    })),
    totalPages: Math.ceil(totalUsers / pageSize),
  };
};
