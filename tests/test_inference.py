import unittest
from unittest.mock import patch, MagicMock
from omegaconf import OmegaConf
import sys, os
import re

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))
from inference import Inference

class TestInference(unittest.TestCase):

    def setUp(self):
        self.vllm_params = {
            "model": "dummy-model",
            "tokenizer": "dummy-tokenizer"
        }        
        self.sampling_params = {"temperature": 0.7}
        self.prompt = OmegaConf.create({
            "system_prompt": "This is a test for MEDICAL_FIELDS",
            "fewshot_examples": [{"question": "What are the symptoms of flu?", "answer": "Fever, cough, sore throat"}],
            "regex": r"The category is: (?P<category>\w+)"
        })
        self.options_file = "tests/options.txt"
        self.progress_file = "tests/progress.json"

        self.mock_dependencies()
        self.inference = Inference(self.vllm_params, self.sampling_params, self.prompt, self.options_file, progress_file=self.progress_file)
        self.mock_tokenizer_vocabulary()

    def tearDown(self):
        self.stop_mocks()
        if os.path.exists(self.inference.progress_file):
            os.remove(self.inference.progress_file)

    def mock_dependencies(self):
        """Mocks external dependencies required for the test."""
        self.mock_model = patch('inference.LLM').start()
        self.mock_tokenizer = patch('inference.get_tokenizer').start()
        patch('inference.load_txt_as_array', return_value=["cardiology", "neurology"]).start()

    def mock_tokenizer_vocabulary(self):
        token_mapping = {
            "What": 1, "is": 2, "cardiology": 3, "neurology": 4, 
            "The": 5, "answer": 6, "easy": 7, "difficult": 8, "category": 9, "is": 10, ".": 11, ":": 12, "?": 13
        }

        def mock_vocabulary(text):
            words = re.findall(r"\w+|[.,;:?!]", text)
            return {"input_ids": [token_mapping[word] for word in words]}

        mock_tokenizer_instance = MagicMock()
        mock_tokenizer_instance.side_effect = mock_vocabulary
        self.inference.tokenizer = mock_tokenizer_instance

    def stop_mocks(self):
        """Stops all active mocks."""
        self.mock_model.stop()
        self.mock_tokenizer.stop()
        patch.stopall()

    def test_initialization(self):
        self.assertEqual(self.inference.model, self.mock_model())
        self.assertEqual(self.inference.tokenizer("What")["input_ids"][0], 1)
        self.assertEqual(self.inference.options, ["cardiology", "neurology"])
        self.assertEqual(self.inference.prompt.system_prompt, "This is a test for cardiology,neurology")
        self.assertIsNotNone(self.inference.sampling_params)
        self.assertIsNotNone(self.inference.pattern)

    def test_generate_chat_template(self):
        question = "What is cardiology?"
        chat_template = self.inference.generate_chat_template(question)
        expected_chat_template = [
            {'role': 'system', 'content': 'This is a test for cardiology,neurology'}, 
            {'role': 'user', 'content': 'What are the symptoms of flu?'}, 
            {'role': 'assistant', 'content': 'Fever, cough, sore throat'}, 
            {'role': 'user', 'content': 'What is cardiology?'}
        ]
        self.assertEqual(chat_template, expected_chat_template)

    def test_get_tokens(self):
        text = "What is cardiology?"
        tokens = self.inference.get_tokens(text)
        self.assertEqual(tokens, [1, 10, 3, 13])

    def test_generate_inputs(self):
        questions = ["What is cardiology?", "What is neurology?"]
        self.inference.tokenizer.apply_chat_template.side_effect = [[1, 2], [3, 4]]
        inputs = self.inference.generate_inputs(questions)
        self.assertEqual(inputs, [[1, 2], [3, 4]])

    def test_predict(self):
        self.mock_tokenizer_vocabulary()
        input_data = ["What is cardiology?", "What is neurology?"]
        mock_outputs = [
            MagicMock(outputs=[MagicMock(text="The answer is easy. The category is: cardiology.", cumulative_logprob=-500)]),
            MagicMock(outputs=[MagicMock(text="The answer is difficult. The category is: neurology.", cumulative_logprob=-100)])
        ]


        self.mock_model.return_value.generate.return_value = mock_outputs
        preds, logprobs, cot = self.inference.predict(input_data)
        self.assertEqual(tuple(preds), ("cardiology", "neurology"))
        self.assertEqual(tuple(logprobs), (-500, -100))
        self.assertEqual(tuple(cot), (
            "The answer is easy. The category is: cardiology.",
            "The answer is difficult. The category is: neurology."
        ))

    def test_save_and_load_progress(self):
        preds = ["cardiology"]
        logprobs = [-500]
        cot = ["The answer is easy. The category is: cardiology."]
        self.inference.save_progress(preds, logprobs, cot, 1)

        loaded_preds, loaded_logprobs, loaded_cot, processed = self.inference.load_progress()
        self.assertEqual(loaded_preds, preds)
        self.assertEqual(loaded_logprobs, logprobs)
        self.assertEqual(loaded_cot, cot)
        self.assertEqual(processed, 1)

if __name__ == '__main__':
    unittest.main()
