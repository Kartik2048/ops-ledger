import React, { createContext, useContext, useState, useEffect } from 'react';
import { UserResponse, TeamResponse, TeamRole } from '../types/contracts';

interface UserContextType {
  currentUser: UserResponse | null;
  users: UserResponse[];
  teams: TeamResponse[];
  setCurrentUser: (user: UserResponse) => void;
  getUserTeamRole: (teamId: string) => TeamRole | null;
  replayMode: boolean;
  setReplayMode: React.Dispatch<React.SetStateAction<boolean>>;
  lastIdempotencyKey: string | null;
  setLastIdempotencyKey: (key: string | null) => void;
  isLoading: boolean;
}

const UserContext = createContext<UserContextType | undefined>(undefined);

export const UserProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [users, setUsers] = useState<UserResponse[]>([]);
  const [teams, setTeams] = useState<TeamResponse[]>([]);
  const [currentUser, setCurrentUser] = useState<UserResponse | null>(null);
  const [replayMode, setReplayMode] = useState<boolean>(false);
  const [lastIdempotencyKey, setLastIdempotencyKey] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);

  // Fetch users and teams on initial load
  useEffect(() => {
    const fetchContextData = async () => {
      try {
        const [usersRes, teamsRes] = await Promise.all([
          fetch('/api/users'),
          fetch('/api/teams'),
        ]);

        if (usersRes.ok && teamsRes.ok) {
          const usersData: UserResponse[] = await usersRes.json();
          const teamsData: TeamResponse[] = await teamsRes.json();
          setUsers(usersData);
          setTeams(teamsData);

          // Default to Alice Chen (Lead) if available
          const leadUser = usersData.find(u => u.full_name.includes('Alice')) || usersData[0];
          if (leadUser) {
            setCurrentUser(leadUser);
          }
        }
      } catch (err) {
        console.error('Failed to initialize user and team context', err);
      } finally {
        setIsLoading(false);
      }
    };

    fetchContextData();
  }, []);

  // Compute active user's role within a specific team
  const getUserTeamRole = (teamId: string): TeamRole | null => {
    if (!currentUser || !teams.length) return null;
    const team = teams.find(t => t.id === teamId);
    if (!team || !team.memberships) return null;
    const membership = team.memberships.find(m => m.user_id === currentUser.id);
    return membership ? membership.role : null;
  };

  return (
    <UserContext.Provider
      value={{
        currentUser,
        users,
        teams,
        setCurrentUser,
        getUserTeamRole,
        replayMode,
        setReplayMode,
        lastIdempotencyKey,
        setLastIdempotencyKey,
        isLoading,
      }}
    >
      {children}
    </UserContext.Provider>
  );
};

export const useUser = (): UserContextType => {
  const context = useContext(UserContext);
  if (!context) {
    throw new Error('useUser must be used within a UserProvider');
  }
  return context;
};
