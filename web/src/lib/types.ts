// Mirrors api/models.py exactly (section 5.5 / 9.9). Only the accounts
// surface has real backend models this wave — everything else stays a 501
// stub, so there is nothing further to type yet.

export type Role = "admin" | "member";

/** GET /users item — api/models.py UserOut. */
export interface RosterUser {
  id: string;
  display_name: string;
  role: Role;
  document_count: number;
  last_seen_at: string | null;
}

/** GET /users — api/models.py UsersListOut. */
export interface UsersListResponse {
  items: RosterUser[];
}

/** The user embedded in POST /auth/session and GET /auth/me — api/models.py MeUser. */
export interface MeUser {
  id: string;
  display_name: string;
  role: Role;
}

/** GET /auth/me — api/models.py MeOut. */
export interface MeResponse {
  user: MeUser;
}

/** POST /auth/session — api/models.py SessionOut. */
export interface SessionResponse {
  user: MeUser;
}

/** The section 9 error envelope, produced by every 4xx/5xx. */
export interface ApiErrorBody {
  error: {
    code: string;
    message: string;
    details: unknown;
  };
}
