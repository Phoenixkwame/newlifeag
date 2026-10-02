from django.test import TestCase

from members.models import Member

from .forms import SurveyResponseForm
from .models import Survey, SurveyAnswer, SurveyChoice, SurveyQuestion, SurveyResponse
from .services import aggregate_results


class SurveyModelTests(TestCase):
    def test_str_is_the_title(self):
        survey = Survey.objects.create(title="Service Time Preferences")
        self.assertEqual(str(survey), "Service Time Preferences")

    def test_is_open_defaults_to_true(self):
        survey = Survey.objects.create(title="Service Time Preferences")
        self.assertTrue(survey.is_open)


class SurveyQuestionModelTests(TestCase):
    def test_default_type_is_text(self):
        survey = Survey.objects.create(title="Feedback")
        question = SurveyQuestion.objects.create(survey=survey, text="What did you think?")
        self.assertEqual(question.question_type, SurveyQuestion.QuestionType.TEXT)

    def test_questions_ordered_by_order_then_id(self):
        survey = Survey.objects.create(title="Feedback")
        SurveyQuestion.objects.create(survey=survey, text="Second", order=2)
        SurveyQuestion.objects.create(survey=survey, text="First", order=1)
        self.assertEqual(list(survey.questions.values_list("text", flat=True)), ["First", "Second"])


class SurveyResponseModelTests(TestCase):
    def test_one_response_per_member_per_survey(self):
        survey = Survey.objects.create(title="Feedback")
        member = Member.objects.create(first_name="Kojo", last_name="Mensah")
        SurveyResponse.objects.create(survey=survey, member=member)
        with self.assertRaises(Exception):
            SurveyResponse.objects.create(survey=survey, member=member)


class SurveyResponseFormTests(TestCase):
    def setUp(self):
        self.survey = Survey.objects.create(title="Service Times")
        self.choice_question = SurveyQuestion.objects.create(
            survey=self.survey, text="Preferred time?", question_type=SurveyQuestion.QuestionType.CHOICE, order=1
        )
        self.choice_a = SurveyChoice.objects.create(question=self.choice_question, text="8am")
        self.choice_b = SurveyChoice.objects.create(question=self.choice_question, text="10:30am")
        self.text_question = SurveyQuestion.objects.create(survey=self.survey, text="Anything else?", order=2)

    def test_builds_one_field_per_question(self):
        form = SurveyResponseForm(self.survey)
        self.assertEqual(len(form.fields), 2)

    def test_choice_field_offers_only_that_questions_choices(self):
        form = SurveyResponseForm(self.survey)
        field_name = form.question_field_names[self.choice_question.id]
        self.assertIn(self.choice_a, form.fields[field_name].queryset)
        self.assertIn(self.choice_b, form.fields[field_name].queryset)

    def test_all_fields_are_optional(self):
        form = SurveyResponseForm(self.survey, data={})
        self.assertTrue(form.is_valid())


class AggregateResultsTests(TestCase):
    def setUp(self):
        self.survey = Survey.objects.create(title="Service Times")
        self.choice_question = SurveyQuestion.objects.create(
            survey=self.survey, text="Preferred time?", question_type=SurveyQuestion.QuestionType.CHOICE
        )
        self.choice_a = SurveyChoice.objects.create(question=self.choice_question, text="8am")
        self.choice_b = SurveyChoice.objects.create(question=self.choice_question, text="10:30am")
        self.text_question = SurveyQuestion.objects.create(survey=self.survey, text="Anything else?")

    def test_choice_counts_include_zero_count_choices(self):
        member = Member.objects.create(first_name="Kojo", last_name="Mensah")
        response = SurveyResponse.objects.create(survey=self.survey, member=member)
        SurveyAnswer.objects.create(response=response, question=self.choice_question, choice=self.choice_a)

        results = aggregate_results(self.survey)
        choice_result = next(r for r in results if r["question"] == self.choice_question)
        counts = dict(choice_result["choice_counts"])
        self.assertEqual(counts[self.choice_a], 1)
        self.assertEqual(counts[self.choice_b], 0)

    def test_text_answers_skip_blanks(self):
        member1 = Member.objects.create(first_name="Kojo", last_name="Mensah")
        member2 = Member.objects.create(first_name="Ama", last_name="Boateng")
        response1 = SurveyResponse.objects.create(survey=self.survey, member=member1)
        response2 = SurveyResponse.objects.create(survey=self.survey, member=member2)
        SurveyAnswer.objects.create(response=response1, question=self.text_question, text_answer="Great service!")
        SurveyAnswer.objects.create(response=response2, question=self.text_question, text_answer="")

        results = aggregate_results(self.survey)
        text_result = next(r for r in results if r["question"] == self.text_question)
        self.assertEqual(len(text_result["text_answers"]), 1)
        self.assertEqual(text_result["text_answers"][0].text_answer, "Great service!")
