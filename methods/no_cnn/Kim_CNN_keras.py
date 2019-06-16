import os
#os.environ["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"   # see issue #152
#os.environ["CUDA_VISIBLE_DEVICES"] = ""

from keras.layers import Conv1D, MaxPool1D, Flatten
from keras.layers import Input, Embedding, Dense
from keras.layers import Dropout
from keras.models import Model
from sklearn.metrics import f1_score, classification_report
import numpy as np
import keras
from imblearn.over_sampling import RandomOverSampler
from imblearn.under_sampling import RandomUnderSampler
# input > embedding > conv1d > max pooling > dense > dropout > sigmoid


# load data
def load_data_iter(filename, batch_size=128, train=True):
    labels = []
    docs = []

    with open(filename) as dfile:
        dfile.readline() # skip column names
        for line in dfile:
            infos = line.strip().split('\t')
            labels.append(int(infos[-1]))
            docs.append([int(item) for item in infos[1].split()])

    if train:
        # over sampling to balance data
        ros = RandomUnderSampler(random_state=33)
        sample_indices = [[item] for item in list(range(len(docs)))]
        sample_indices, labels = ros.fit_sample(sample_indices, labels)
        docs = [docs[item[0]] for item in sample_indices]
        
        # check if the number of training example exceeds 150000
        if len(docs) > 200000:
            indices = list(range(len(docs)))
            np.random.seed(33) # for reproducibility
            np.random.shuffle(indices)
            indices = indices[:200000]
            

            # get the first 200000 data
            docs = [docs[tmp] for tmp in indices]
            labels = [labels[tmp] for tmp in indices]

    docs = np.asarray(docs)

    steps = int(len(docs) / batch_size)
    if len(docs) % batch_size != 0:
        steps += 1

    for idx in range(steps):
        batch_data = docs[idx*batch_size: (idx+1)*batch_size]
        batch_label = labels[idx*batch_size: (idx+1)*batch_size]

        yield batch_data, batch_label


def run_kim_CNN(data_name):
    """
    This file will use DANN's existing data

    """
    print('Working on: '+data_name)
    # load w2v weights for the Embedding
    weights = np.load(open('../../data/weight/'+data_name+'.npy', 'rb'))

    text_input = Input(shape=(50, ), dtype='int32')
    embed = Embedding(
        weights.shape[0], weights.shape[1], # size of data embedding
        weights=[weights], input_length=50,
        trainable=True,
        name='embedding')(text_input)

    conv3 = Conv1D(
        kernel_size=3, filters=100,
        kernel_regularizer=keras.regularizers.l1_l2(0, 0.03),
        padding='same',
    )(embed)
    maxp3 = MaxPool1D()(conv3)
    conv4 = Conv1D(
        kernel_size=4, filters=100,
        kernel_regularizer=keras.regularizers.l1_l2(0, 0.03),
        padding='same',
    )(embed)
    maxp4 = MaxPool1D()(conv4)
    conv5 = Conv1D(
        kernel_size=5, filters=100,
        kernel_regularizer=keras.regularizers.l1_l2(0, 0.03),
        padding='same',
    )(embed)
    maxp5 = MaxPool1D()(conv5)

    # merge
    merge_convs = keras.layers.concatenate([maxp3, maxp4, maxp5], axis=-1)

    # flatten
    flat_l = Flatten()(merge_convs)

    # dense
    dense_l = Dense(100, activation='relu')(flat_l)
    dp_l = Dropout(0.2)(dense_l)

    # output
    pred_l = Dense(1, activation='sigmoid')(dp_l)

    # model
    model = Model(inputs=text_input, outputs=pred_l)
    model.compile(optimizer='adadelta', loss='binary_crossentropy', metrics=['accuracy'])

    print(model.summary())
    best_valid_f1 = 0.0

    # fit the model
    epoch_num = 20
    train_path = '../../data_indices/' + data_name + '/' + data_name + '.train'
    valid_path = '../../data_indices/' + data_name + '/' + data_name + '.dev'
    test_path = '../../data_indices/' + data_name + '/' + data_name + '.test'

    for e in range(epoch_num):
        accuracy = 0.0
        loss = 0.0
        step = 1

        print('--------------Epoch: {}--------------'.format(e))

        train_iter = load_data_iter(train_path)
        # train sentiment
        # train on batches
        for x_train, y_train in train_iter:
            # skip only 1 class in the training data
            if len(np.unique(y_train)) == 1:
                continue
            
            # train sentiment model
            tmp_senti = model.train_on_batch(
                x_train, y_train,
                class_weight= {1:1, 0:1.2}#{1:5, 0:1}#'auto'
            )
            # calculate loss and accuracy
            loss += tmp_senti[0]
            loss_avg = loss / step
            accuracy += tmp_senti[1]
            accuracy_avg = accuracy / step

            if step % 40 == 0:
                print('Step: {}'.format(step))
                print('\tLoss: {}.'.format(loss_avg))
                print('\tAccuracy: {}.'.format(accuracy_avg))
                print('-------------------------------------------------')
            step += 1

        # each epoch try the valid data, get the best valid-weighted-f1 score
        print('Validating....................................................')
        valid_iter = load_data_iter(valid_path, train=False)
        y_preds_valids = []
        y_valids = []
        for x_valid, y_valid in valid_iter:
            x_valid = np.asarray(x_valid)
            tmp_preds_valid = model.predict(x_valid)
            for item_tmp in tmp_preds_valid:
                y_preds_valids.append(np.round(item_tmp[0]))
            for item_tmp in y_valid:
                y_valids.append(int(item_tmp))
        f1_valid = f1_score(y_true=y_preds_valids, y_pred=y_valids, average='weighted')
        print('Validating f1-weighted score: ' + str(f1_valid))

        # if the validation f1 score is good, then test
        if f1_valid > best_valid_f1:
            best_valid_f1 = f1_valid
            test_iter = load_data_iter(test_path, train=False)
            y_preds = []
            y_tests = []
            for x_test, y_test in test_iter:
                x_test = np.asarray(x_test)
                tmp_preds = model.predict(x_test)
                for item_tmp in tmp_preds:
                    y_preds.append(np.round(item_tmp[0]))
                for item_tmp in y_test:
                    y_tests.append(int(item_tmp))
            test_result = open('./results.txt', 'a')
            test_result.write(data_name + '\n')
            test_result.write('Epoch ' + str(e) + '..................................................\n')
            test_result.write(str(f1_score(y_true=y_tests, y_pred=y_preds, average='weighted')) + '\n')
            test_result.write('#####\n\n')
            test_result.write(classification_report(y_true=y_tests, y_pred=y_preds, digits=3))
            test_result.write('...............................................................\n\n')
            test_result.flush()


if __name__ == '__main__':
    data_list = [
        'twitter',
        'amazon',
        'yelp_hotel',
        'yelp_rest',
    ]
    for data_name in data_list:
        run_kim_CNN(data_name)
