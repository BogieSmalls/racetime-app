from django.conf import settings
from django.http import Http404
from django.urls import path, include
from django.views.generic import RedirectView, TemplateView
from oauth2_provider import views as oauth2_views

from . import views
from .throttling import throttle_view


def protected(view, policy, bucket, methods=None):
    return throttle_view(policy, bucket=bucket, methods=methods)(view)


def disabled_public_route(request, *args, **kwargs):
    """Keep legacy bookmarks deterministic without exposing disabled views."""
    raise Http404


if settings.RT_PUBLIC_PASSWORD_AUTH:
    password_account_patterns = [
        path('security', views.EditAccountSecurity.as_view(), name='edit_account_security'),
        path('login', views.Login.as_view(), name='login'),
        path('create', views.CreateAccount.as_view(), name='create_account'),
        path('derp', views.PasswordResetView.as_view(), name='password_reset'),
        path('derp/done', views.PasswordResetDoneView.as_view(), name='password_reset_done'),
        path(
            'reset/<uidb64>/<token>',
            views.PasswordResetConfirmView.as_view(),
            name='password_reset_confirm',
        ),
        path('reset/complete', views.PasswordResetCompleteView.as_view(), name='password_reset_complete'),
    ]
else:
    password_account_patterns = [
        path('security', disabled_public_route, name='edit_account_security'),
        path('login', disabled_public_route, name='login'),
        path('create', disabled_public_route, name='create_account'),
        path('derp', disabled_public_route, name='password_reset'),
        path('derp/done', disabled_public_route, name='password_reset_done'),
        path('reset/<uidb64>/<token>', disabled_public_route, name='password_reset_confirm'),
        path('reset/complete', disabled_public_route, name='password_reset_complete'),
    ]

if settings.RT_PATREON_ENABLED:
    patreon_account_patterns = [
        path('patreon_auth', views.PatreonAuth.as_view(), name='patreon_auth'),
        path('patreon_disconnect', views.PatreonDisconnect.as_view(), name='patreon_disconnect'),
        path('patreon_refresh', views.PatreonRefresh.as_view(), name='patreon_refresh'),
    ]
else:
    patreon_account_patterns = [
        path('patreon_auth', disabled_public_route, name='patreon_auth'),
        path('patreon_disconnect', disabled_public_route, name='patreon_disconnect'),
        path('patreon_refresh', disabled_public_route, name='patreon_refresh'),
    ]

account_patterns = [
    path('auth', views.LoginRegister.as_view(), name='login_or_register'),
    path(
        'discord',
        protected(views.discord_initiate, 'discord_auth', 'discord_initiate'),
        name='discord_initiate',
    ),
    path(
        'discord/callback',
        protected(views.discord_callback, 'discord_auth', 'discord_callback'),
        name='discord_callback',
    ),
    path(
        'discord/create',
        protected(views.discord_create_account, 'discord_auth', 'discord_create_account'),
        name='discord_create_account',
    ),
    path('connections', views.EditAccountConnections.as_view(), name='edit_account_connections'),
    path('standing', views.AccountStanding.as_view(), name='account_standing'),
    path('teams', views.EditAccountTeams.as_view(), name='edit_account_teams'),
    path(
        'teams/create',
        protected(views.CreateTeam.as_view(), 'profile_mutation', 'create_team', ('POST',)),
        name='create_team',
    ),
    path(
        'teams/join/<str:team>',
        protected(views.JoinTeam.as_view(), 'profile_mutation', 'join_team', ('POST',)),
        name='join_team',
    ),
    path(
        'teams/leave/<str:team>',
        protected(views.LeaveTeam.as_view(), 'profile_mutation', 'leave_team', ('POST',)),
        name='leave_team',
    ),
    path('logout', views.Logout.as_view(), name='logout'),
    path(
        'delete',
        protected(views.DeleteAccount.as_view(), 'profile_mutation', 'delete_account', ('POST',)),
        name='delete_account',
    ),
    path(
        'twitch_auth',
        protected(views.TwitchAuth.as_view(), 'profile_mutation', 'twitch_auth', ('GET',)),
        name='twitch_auth',
    ),
    path(
        'twitch_disconnect',
        protected(views.TwitchDisconnect.as_view(), 'profile_mutation', 'twitch_disconnect', ('POST',)),
        name='twitch_disconnect',
    ),
]
account_patterns.extend(password_account_patterns)
account_patterns.extend(patreon_account_patterns)

request_category_view = (
    views.RequestCategory.as_view()
    if settings.RT_PUBLIC_CATEGORY_REQUESTS
    else disabled_public_route
)

urlpatterns = [
    path('healthz', views.healthz, name='healthz'),
    path('internal/readyz', views.internal_readyz, name='internal_readyz'),
    path(
        'privacy',
        TemplateView.as_view(template_name='racetime/policy/privacy.html'),
        name='privacy_policy',
    ),
    path(
        'acceptable-use',
        TemplateView.as_view(
            template_name='racetime/policy/acceptable_use.html'
        ),
        name='acceptable_use_policy',
    ),
    path(
        'account-deletion',
        TemplateView.as_view(
            template_name='racetime/policy/account_deletion.html'
        ),
        name='account_deletion_policy',
    ),
    path(
        'contact',
        TemplateView.as_view(template_name='racetime/policy/contact.html'),
        name='contact_policy',
    ),

    path(
        'account',
        protected(views.EditAccount.as_view(), 'profile_mutation', 'edit_account', ('POST',)),
        name='edit_account',
    ),
    path('account/', include(account_patterns)),

    path('o/', include([
        path(
            'authorize',
            protected(views.OAuthAuthorize.as_view(), 'oauth_decision', 'oauth2_authorize', ('POST',)),
            name='oauth2_authorize',
        ),
        path(
            'token',
            protected(oauth2_views.TokenView.as_view(), 'oauth_decision', 'oauth2_token', ('POST',)),
            name='oauth2_token',
        ),
        path(
            'revoke_token',
            protected(oauth2_views.RevokeTokenView.as_view(), 'oauth_decision', 'oauth2_revoke', ('POST',)),
            name='oauth2_revoke',
        ),

        path(
            'delete/<pk>',
            protected(views.OAuthDeleteToken.as_view(), 'profile_mutation', 'oauth2_delete', ('POST',)),
            name='oauth2_delete',
        ),
        path('done', views.OAuthDone.as_view(), name='oauth2_authorize_done'),
        path('userinfo', views.OAuthUserInfo.as_view(), name='oauth2_userinfo'),
        path('<str:category>/data', views.OAuthCategoryData.as_view(), name='oauth2_category_data'),
        path(
            '<str:category>/startrace',
            protected(views.OAuthCreateRace.as_view(), 'race_create', 'oauth2_create_race', ('POST',)),
            name='oauth2_create_race',
        ),
        path(
            '<str:category>/<str:race>/edit',
            protected(views.OAuthEditRace.as_view(), 'admin_mutation', 'oauth2_edit_race', ('POST',)),
            name='oauth2_edit_race',
        ),
        path('<str:category>/<str:race>/monitor/pin/<str:message>', protected(views.OAuthRaceChatPin.as_view(), 'admin_mutation', 'oauth2_chat_pin', ('POST',)), name='oauth2_chat_pin'),
        path('<str:category>/<str:race>/monitor/unpin/<str:message>', protected(views.OAuthRaceChatUnpin.as_view(), 'admin_mutation', 'oauth2_chat_unpin', ('POST',)), name='oauth2_chat_unpin'),
        path('<str:category>/<str:race>/monitor/purge/<str:message>', protected(views.OAuthRaceChatPurge.as_view(), 'admin_mutation', 'oauth2_chat_purge', ('POST',)), name='oauth2_chat_purge'),
        path('<str:category>/<str:race>/monitor/delete/<str:message>', protected(views.OAuthRaceChatDelete.as_view(), 'admin_mutation', 'oauth2_chat_delete', ('POST',)), name='oauth2_chat_delete'),
    ])),

    path('team/', include([
        path('<str:team>.json', views.TeamData.as_view()),
        path('<str:team>', views.Team.as_view(), name='team'),
        path('<str:team>/', include([
            path('data', views.TeamData.as_view(), name='team_data'),
            path('manage/', include([
                path('edit', protected(views.EditTeam.as_view(), 'admin_mutation', 'edit_team', ('POST',)), name='edit_team'),
                path('delete', protected(views.DeleteTeam.as_view(), 'admin_mutation', 'delete_team', ('POST',)), name='delete_team'),
                path('members', views.TeamMembers.as_view(), name='team_members'),
                path('members/add', protected(views.AddTeamMember.as_view(), 'admin_mutation', 'team_member_add', ('POST',)), name='team_member_add'),
                path('members/remove', protected(views.RemoveTeamMember.as_view(), 'admin_mutation', 'team_member_remove', ('POST',)), name='team_member_remove'),
                path('members/add-owner', protected(views.AddTeamOwner.as_view(), 'admin_mutation', 'team_owner_add', ('POST',)), name='team_owner_add'),
                path('members/remove-owner', protected(views.RemoveTeamOwner.as_view(), 'admin_mutation', 'team_owner_remove', ('POST',)), name='team_owner_remove'),
                path('log', views.TeamAudit.as_view(), name='team_audit_log'),
            ])),
        ])),
    ])),

    path('autocomplete/', include([
        path(
            'user',
            protected(views.AutocompleteUser.as_view(), 'lookup', 'autocomplete_user', ('GET',)),
            name='autocomplete_user',
        ),
    ])),

    path(
        '',
        RedirectView.as_view(url='/z1rr', permanent=True),
        name='home',
    ),
    path(
        'search',
        protected(views.Search.as_view(), 'lookup', 'search', ('GET',)),
        name='search',
    ),
    path('request_category', request_category_view, name='request_category'),
    path('races/data', views.RaceListData.as_view(), name='race_list_data'),
    path('races.json', views.RaceListData.as_view()),
    path(
        'user/search',
        protected(views.AutocompleteUser.as_view(), 'lookup', 'autocomplete_user', ('GET',)),
        name='autocomplete_user',
    ),
    path('user/<str:user>', views.ViewProfile.as_view(), name='view_profile'),
    path('user/<str:user>.json', views.UserProfileData.as_view()),
    path('user/<str:user>/', include([
        path('data', views.UserProfileData.as_view(), name='user_profile_data'),
        path('races/data', views.UserRaceData.as_view(), name='user_race_list_data'),
        path('races.json', views.UserRaceData.as_view()),
    ])),
    path('user/<str:user>/<str:name>', views.ViewProfile.as_view(), name='view_profile'),

    path('categories/data', views.CategoryListData.as_view(), name='category_list_data'),
    path('<str:category>.json', views.CategoryData.as_view()),
    path('<str:category>', views.Category.as_view(), name='category'),
    path('<str:category>/', include([
        path('data', views.CategoryData.as_view(), name='category_data'),
        path('races/data', views.CategoryRaceData.as_view(), name='category_race_list_data'),
        path('races.json', views.CategoryRaceData.as_view()),
        path('manage/', include([
            path('edit', protected(views.EditCategory.as_view(), 'admin_mutation', 'edit_category', ('POST',)), name='edit_category'),
            path('deactivate', protected(views.DeactivateCategory.as_view(), 'admin_mutation', 'category_deactivate', ('POST',)), name='category_deactivate'),
            path('reactivate', protected(views.ReactivateCategory.as_view(), 'admin_mutation', 'category_reactivate', ('POST',)), name='category_reactivate'),
            path('goals', views.GoalList.as_view(), name='category_goals'),
            path('goals/new', protected(views.CreateGoal.as_view(), 'admin_mutation', 'new_category_goal', ('POST',)), name='new_category_goal'),
            path('goals/<str:goal>/edit', protected(views.EditGoal.as_view(), 'admin_mutation', 'edit_category_goal', ('POST',)), name='edit_category_goal'),
            path('bots', views.BotList.as_view(), name='category_bots'),
            path('bots/new', protected(views.CreateBot.as_view(), 'admin_mutation', 'new_category_bot', ('POST',)), name='new_category_bot'),
            path('bots/<str:bot>/deactivate', protected(views.DeactivateBot.as_view(), 'admin_mutation', 'deactivate_category_bot', ('POST',)), name='deactivate_category_bot'),
            path('bots/<str:bot>/reactivate', protected(views.ReactivateBot.as_view(), 'admin_mutation', 'reactivate_category_bot', ('POST',)), name='reactivate_category_bot'),
            path('mods', views.CategoryModerators.as_view(), name='category_mods'),
            path('mods/add_owner', protected(views.AddOwner.as_view(), 'admin_mutation', 'category_owners_add', ('POST',)), name='category_owners_add'),
            path('mods/remove_owner', protected(views.RemoveOwner.as_view(), 'admin_mutation', 'category_owners_remove', ('POST',)), name='category_owners_remove'),
            path('mods/add_moderator', protected(views.AddModerator.as_view(), 'admin_mutation', 'category_mods_add', ('POST',)), name='category_mods_add'),
            path('mods/remove_moderator', protected(views.RemoveModerator.as_view(), 'admin_mutation', 'category_mods_remove', ('POST',)), name='category_mods_remove'),
            path('teams', protected(views.CategoryTeams.as_view(), 'admin_mutation', 'category_teams', ('POST',)), name='category_teams'),
            path('log', views.CategoryAudit.as_view(), name='category_audit_log'),
            path('emotes', views.CategoryManageEmotes.as_view(), name='category_emotes'),
            path('emotes/add', protected(views.AddEmote.as_view(), 'admin_mutation', 'category_emotes_add', ('POST',)), name='category_emotes_add'),
            path('emotes/<str:emote_name>/remove', protected(views.RemoveEmote.as_view(), 'admin_mutation', 'category_emotes_remove', ('POST',)), name='category_emotes_remove'),
        ])),
        path('leaderboards', views.CategoryLeaderboards.as_view(), name='leaderboards'),
        path('leaderboards/data', views.CategoryLeaderboardsData.as_view(), name='leaderboards_data'),
        path('leaderboards.json', views.CategoryLeaderboardsData.as_view()),
        path('emotes', views.CategoryEmotes.as_view(), name='category_list_emotes'),
        path('record', views.CategoryRecorder.as_view(), name='category_record'),
        path(
            'startrace',
            protected(views.CreateRace.as_view(), 'race_create', 'create_race', ('POST',)),
            name='create_race',
        ),
        path('star', protected(views.FavouriteCategory.as_view(), 'profile_mutation', 'star', ('POST',)), name='star'),
        path('unstar', protected(views.UnfavouriteCategory.as_view(), 'profile_mutation', 'unstar', ('POST',)), name='unstar'),
    ])),

    path('<str:category>/<str:race>.csv', views.RaceCSV.as_view()),
    path('<str:category>/<str:race>.json', views.RaceData.as_view()),
    path('<str:category>/<str:race>.log', views.RaceChatLog.as_view()),
    path('<str:category>/<str:race>.txt', views.RaceChatLog.as_view()),
    path('<str:category>/<str:race>', views.Race.as_view(), name='race'),
    path('<str:category>/<str:race>/', include([
        path('csv', views.RaceCSV.as_view(), name='race_csv'),
        path('data', views.RaceData.as_view(), name='race_data'),
        path('mini', views.RaceMini.as_view(), name='race_mini'),
        path('livesplit', views.RaceLiveSplit.as_view(), name='race_livesplit'),
        path('log', views.RaceChatLog.as_view(), name='race_log'),
        path('renders', views.RaceRenders.as_view(), name='race_renders'),
        path('spectate', views.RaceSpectate.as_view(), name='race_spectate'),

        path('message', protected(views.Message.as_view(), 'chat_mutation', 'message', ('POST',)), name='message'),
        path('get_dm/<str:message>', views.RaceChatDM.as_view(), name='chat_dm'),
        path(
            'join',
            protected(views.Join.as_view(), 'in_race_transition', 'join', ('POST',)),
            name='join',
        ),
        path(
            'leave',
            protected(views.Leave.as_view(), 'in_race_transition', 'leave', ('POST',)),
            name='leave',
        ),
        path(
            'request_invite',
            protected(views.RequestInvite.as_view(), 'in_race_transition', 'request_invite', ('POST',)),
            name='request_invite',
        ),
        path(
            'cancel_invite',
            protected(views.CancelInvite.as_view(), 'in_race_transition', 'cancel_invite', ('POST',)),
            name='cancel_invite',
        ),
        path(
            'accept_invite',
            protected(views.AcceptInvite.as_view(), 'in_race_transition', 'accept_invite', ('POST',)),
            name='accept_invite',
        ),
        path(
            'decline_invite',
            protected(views.DeclineInvite.as_view(), 'in_race_transition', 'decline_invite', ('POST',)),
            name='decline_invite',
        ),
        path(
            'ready',
            protected(views.Ready.as_view(), 'in_race_transition', 'ready', ('POST',)),
            name='ready',
        ),
        path(
            'unready',
            protected(views.Unready.as_view(), 'in_race_transition', 'unready', ('POST',)),
            name='unready',
        ),
        path(
            'done',
            protected(views.Done.as_view(), 'in_race_transition', 'done', ('POST',)),
            name='done',
        ),
        path(
            'undone',
            protected(views.Undone.as_view(), 'in_race_transition', 'undone', ('POST',)),
            name='undone',
        ),
        path(
            'split',
            protected(views.Split.as_view(), 'in_race_transition', 'split', ('POST',)),
            name='split',
        ),
        path(
            'forfeit',
            protected(views.Forfeit.as_view(), 'in_race_transition', 'forfeit', ('POST',)),
            name='forfeit',
        ),
        path(
            'unforfeit',
            protected(views.Unforfeit.as_view(), 'in_race_transition', 'unforfeit', ('POST',)),
            name='unforfeit',
        ),
        path('add_comment', protected(views.AddComment.as_view(), 'profile_mutation', 'add_comment', ('POST',)), name='add_comment'),
        path('add_comment', protected(views.AddComment.as_view(), 'profile_mutation', 'change_comment', ('POST',)), name='change_comment'),
        path(
            'set_team',
            protected(views.SetTeam.as_view(), 'in_race_transition', 'set_team', ('POST',)),
            name='set_team',
        ),
        path('available_teams', views.RaceAvailableTeams.as_view(), name='available_teams'),

        path('monitor/', include([
            path('edit', protected(views.EditRace.as_view(), 'admin_mutation', 'edit_race', ('POST',)), name='edit_race'),
            path('open', protected(views.MakeOpen.as_view(), 'admin_mutation', 'make_open', ('POST',)), name='make_open'),
            path('invitational', protected(views.MakeInvitational.as_view(), 'admin_mutation', 'make_invitational', ('POST',)), name='make_invitational'),
            path(
                'begin',
                protected(views.BeginRace.as_view(), 'in_race_transition', 'begin_race', ('POST',)),
                name='begin_race',
            ),
            path(
                'cancel',
                protected(views.CancelRace.as_view(), 'in_race_transition', 'cancel_race', ('POST',)),
                name='cancel_race',
            ),
            path('invite', protected(views.InviteToRace.as_view(), 'admin_mutation', 'invite_to_race', ('POST',)), name='invite_to_race'),
            path('record', protected(views.RecordRace.as_view(), 'admin_mutation', 'record_race', ('POST',)), name='record_race'),
            path('unrecord', protected(views.UnrecordRace.as_view(), 'admin_mutation', 'unrecord_race', ('POST',)), name='unrecord_race'),
            path('hold', protected(views.HoldRace.as_view(), 'in_race_transition', 'hold_race', ('POST',)), name='hold_race'),
            path('unhold', protected(views.UnholdRace.as_view(), 'in_race_transition', 'unhold_race', ('POST',)), name='unhold_race'),
            path('rematch', protected(views.Rematch.as_view(), 'race_create', 'rematch', ('POST',)), name='rematch'),
            path('pin/<str:message>', protected(views.RaceChatPin.as_view(), 'admin_mutation', 'chat_pin', ('POST',)), name='chat_pin'),
            path('unpin/<str:message>', protected(views.RaceChatUnpin.as_view(), 'admin_mutation', 'chat_unpin', ('POST',)), name='chat_unpin'),
            path('delete/<str:message>', protected(views.RaceChatDelete.as_view(), 'admin_mutation', 'chat_delete', ('POST',)), name='chat_delete'),
            path('purge/<str:message>', protected(views.RaceChatPurge.as_view(), 'admin_mutation', 'chat_purge', ('POST',)), name='chat_purge'),

            path('<str:entrant>/', include([
                path('edit', protected(views.EditRaceResult.as_view(), 'admin_mutation', 'edit_race_result', ('POST',)), name='edit_race_result'),
                path('accept_request', protected(views.AcceptRequest.as_view(), 'in_race_transition', 'accept_request', ('POST',)), name='accept_request'),
                path('force_unready', protected(views.ForceUnready.as_view(), 'in_race_transition', 'force_unready', ('POST',)), name='force_unready'),
                path('override_stream', protected(views.OverrideStream.as_view(), 'admin_mutation', 'override_stream', ('POST',)), name='override_stream'),
                path('remove', protected(views.Remove.as_view(), 'in_race_transition', 'remove', ('POST',)), name='remove'),
                path(
                    'disqualify',
                    protected(views.Disqualify.as_view(), 'in_race_transition', 'disqualify', ('POST',)),
                    name='disqualify',
                ),
                path(
                    'undisqualify',
                    protected(views.Undisqualify.as_view(), 'in_race_transition', 'undisqualify', ('POST',)),
                    name='undisqualify',
                ),
                path('add_monitor', protected(views.AddMonitor.as_view(), 'admin_mutation', 'add_monitor', ('POST',)), name='add_monitor'),
                path('remove_monitor', protected(views.RemoveMonitor.as_view(), 'admin_mutation', 'remove_monitor', ('POST',)), name='remove_monitor'),
            ])),
        ])),
    ])),
]
