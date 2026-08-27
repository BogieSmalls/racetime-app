import json
import re

from django.test import TestCase
from django.urls import reverse

from racetime.forms import GoalEditForm, RaceCreationForm
from racetime.models import Category, Goal, Race, User


TTP = 'TTP: Season 5'
LEAGUE = 'League: Season 1'
CASUAL = 'Beat the game - Casual'
EXPECTED = [TTP, LEAGUE, CASUAL]


class GoalSortOrderTests(TestCase):
    """
    Category owners choose the order their goals appear in.

    The three goals below are deliberately arranged so that neither of the
    pre-existing orderings can produce the expected result: alphabetically
    they sort in exactly the reverse order, and the goal given the most races
    is the one that must appear last.
    """

    def setUp(self):
        self.user = User.objects.create_user(
            'owner@z1rracing.invalid',
            name='Council Owner',
        )
        self.category = Category.objects.create(
            name='Zelda 1 Randomizer',
            short_name='Z1R',
            slug='z1rr',
            streaming_required=False,
        )
        # Created back to front, so primary key order disagrees too.
        self.casual = Goal.objects.create(
            category=self.category, name=CASUAL, sort_order=2,
        )
        self.league = Goal.objects.create(
            category=self.category, name=LEAGUE, sort_order=1,
        )
        self.ttp = Goal.objects.create(
            category=self.category, name=TTP, sort_order=0,
        )
        for index in range(3):
            Race.objects.create(
                category=self.category,
                goal=self.casual,
                slug=f'casual-race-{index}',
                opened_by=self.user,
                streaming_required=False,
            )

    def leaderboard_headings(self):
        # The leaderboards page paginates two goals at a time.
        url = reverse('leaderboards', kwargs={'category': self.category.slug})
        headings = []
        for page in (1, 2):
            response = self.client.get(url, {'page': page})
            self.assertEqual(response.status_code, 200)
            headings += [
                heading.strip() for heading in
                re.findall(r'<h4>(.*?)</h4>', response.content.decode(), re.DOTALL)
            ]
        return headings

    def test_leaderboards_page_orders_goals_by_sort_order(self):
        self.assertEqual(self.leaderboard_headings(), EXPECTED)

    def test_race_creation_goal_choices_follow_sort_order(self):
        form = RaceCreationForm(category=self.category, can_moderate=False)

        choices = [str(goal) for goal in form.fields['goal'].queryset]

        self.assertEqual(choices, EXPECTED)

    def test_category_api_data_orders_goals_by_sort_order(self):
        data = json.loads(self.category.dump_json_data())

        self.assertEqual(data['goals'], EXPECTED)

    def test_goal_management_lists_order_by_sort_order(self):
        goals = self.category.goal_set.filter(active=True)

        self.assertEqual([goal.name for goal in goals], EXPECTED)

    def test_goal_edit_form_exposes_sort_order(self):
        form = GoalEditForm(instance=self.ttp)

        self.assertIn('sort_order', form.fields)
