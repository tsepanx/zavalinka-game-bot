from enum import Enum, auto

from telegram import Update, ReplyKeyboardMarkup, Chat, Poll
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, \
    CallbackContext, ConversationHandler, PollAnswerHandler, PollHandler

from bot.controller import StorageController

from wordlist import generate_wordlist


def chat_id_to_room_id(chat_id: int) -> str:
    return str(chat_id)


def room_id_to_chat_id(room_id: str) -> int:
    return int(room_id)


class Bot:
    class State(Enum):
        INIT_STATE = auto()
        WAIT_ANS = auto()
        WAIT_VOTE = auto()
        ROUND_FINISH = auto()

    def __init__(self, token):
        self.token = token
        self.controller = StorageController()

    def start_command(self, update: Update, context: CallbackContext) -> State:
        room_id = chat_id_to_room_id(update.effective_chat.id)
        self.controller.create_room(room_id)
        update.message.reply_text(
            'Hi!\n'
            'All users who want to participate in game should type /add_me.\n'
            'After that type /start_game to start game.'
        )
        return Bot.State.INIT_STATE

    def add_me_command(self, update: Update, context: CallbackContext) -> State:
        room_id = chat_id_to_room_id(update.effective_chat.id)
        if not self.controller.is_user_in_room(room_id, update.effective_user.id):
            self.controller.add_user_to_room(room_id, update.effective_user)
            update.message.reply_text(
                'Done! You have been added to the game. When everybody is ready type /start_game.'
            )
        else:
            update.message.reply_text('You have been already added to the game.')
        return Bot.State.INIT_STATE

    def start_game_command(self, update: Update, context: CallbackContext) -> State:
        room_id = chat_id_to_room_id(update.effective_chat.id)
        if not self.controller.is_user_in_room(room_id, update.effective_user.id):
            update.message.reply_text('You are not a participant of the game, please type /add_me first.')
            return Bot.State.INIT_STATE
        update.message.reply_text('I\'m starting the game.')
        self.controller.start_game(room_id, generate_wordlist(2))
        context.bot.send_message(update.effective_chat.id, 'Game has been set up.')
        context.bot.send_message(
            update.effective_chat.id,
            'When everybody has finished answering, type /vote to start vote.'
        )
        context.bot.send_message(update.effective_chat.id, f'First word: {self.controller.get_current_word(room_id)}')
        for user_id in self.controller.get_users_in_room(room_id):
            sent_message = context.bot.send_message(
                user_id,
                f'First word: {self.controller.get_current_word(room_id)}'
            )
            self.controller.add_user_question_message_id(room_id, user_id, sent_message.message_id)
        return Bot.State.WAIT_ANS

    def vote_command(self, update: Update, context: CallbackContext) -> State:
        room_id = chat_id_to_room_id(update.effective_chat.id)
        all_descriptions = [self.controller.get_current_description(room_id)] + \
                           list(self.controller.get_current_user_descriptions(room_id).values())
        if len(all_descriptions) == 1:
            all_descriptions.append('Placeholder')
        sent_message = update.message.reply_poll(
            f'{self.controller.get_current_word(room_id)}',
            all_descriptions,
            is_anonymous=False,
        )
        self.controller.add_poll(room_id, sent_message.poll.id, sent_message.message_id)
        return Bot.State.WAIT_VOTE

    def vote_poll_answer(self, update: Update, context: CallbackContext):
        room_id = self.controller.get_room_id_by_poll_id(update.poll_answer.poll_id)
        chat_id = room_id_to_chat_id(room_id)
        if room_id is None:
            return
        self.controller.add_user_vote(room_id, update.poll_answer.user.id, update.poll_answer.option_ids[0])

        if len(self.controller.get_user_votes(room_id)) == len(self.controller.get_users_in_room(room_id)):
            context.bot.stop_poll(
                chat_id, self.controller.get_poll_message_id(room_id)
            )
            context.bot.send_message(
                chat_id,
                'Everybody has voted. To see results type /results.'
            )

    def results_command(self, update: Update, context: CallbackContext):
        pass

    def next_command(self, update: Update, context: CallbackContext):
        pass

    def stop_game_command(self, update: Update, context: CallbackContext) -> int:
        update.message.reply_text("Game ended. Type /start if you want to play again.")
        return ConversationHandler.END

    def receive_description_from_user(self, update: Update, context: CallbackContext) -> None:
        if update.effective_chat.type != Chat.PRIVATE:
            return
        room_id = self.controller.get_room_id_by_private_message_id(
            update.effective_user.id,
            update.message.reply_to_message.message_id,
        )
        self.controller.add_user_description(
            room_id,
            update.effective_user.id,
            update.message.text
        )
        update.message.reply_text("Your answer was saved.")

        if len(self.controller.get_users_in_room(room_id)) == \
                len(self.controller.get_current_user_descriptions(room_id)):
            chat_id = room_id_to_chat_id(room_id)
            context.bot.send_message(
                chat_id,
                "All participants have published their answers, you can safely type /vote now."
            )

    def start(self):
        updater = Updater(self.token, use_context=True)

        dispatcher = updater.dispatcher
        dispatcher.add_handler(PollAnswerHandler(self.vote_poll_answer))
        dispatcher.add_handler(ConversationHandler(
            entry_points=[CommandHandler("start", self.start_command)],
            states={
                Bot.State.INIT_STATE: [
                    CommandHandler("add_me", self.add_me_command),
                    CommandHandler("start_game", self.start_game_command)
                ],
                Bot.State.WAIT_ANS: [CommandHandler("vote", self.vote_command)],
                Bot.State.WAIT_VOTE: [CommandHandler("results", self.results_command)],
                Bot.State.ROUND_FINISH: [CommandHandler("next", self.next_command)],
            },
            fallbacks=[CommandHandler("stop_game", self.stop_game_command)],
            per_chat=True,
            per_user=False,
            per_message=False,
            allow_reentry=True,
        ))
        dispatcher.add_handler(MessageHandler(Filters.reply, self.receive_description_from_user))

        updater.start_polling()

        updater.idle()
